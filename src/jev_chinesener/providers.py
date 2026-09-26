import asyncio
import math
import os
from dataclasses import dataclass, field
from typing import Protocol

from .config import Settings
from .models import Judgment
from .questions import Question


class ProviderError(RuntimeError):
    """Sanitized upstream error: never include credentials or raw HTTP responses."""


@dataclass
class BatchResult:
    answers: dict[str, Judgment] = field(default_factory=dict)
    model: str | None = None
    requests: int = 0
    usage: dict[str, int] = field(default_factory=dict)


class Judge(Protocol):
    source: str

    async def evaluate(self, state: dict, questions: list[Question]) -> BatchResult: ...


class MockJudge:
    """Reproducible test doubles, not a simulation or measurement of Jev accuracy."""

    source = "mock"

    async def evaluate(self, state: dict, questions: list[Question]) -> BatchResult:
        answers = {}
        for question in questions:
            if question.kind == "noul":
                answer = Judgment(question_id=question.id, kind="noul", source="mock", noul=0.5)
            else:
                choice = question.hint if question.hint in question.criteria else "unknown"
                if choice not in question.criteria:
                    choice = next(iter(question.criteria))
                count = len(question.criteria)
                probabilities = {
                    key: (0.7 if key == choice else 0.3 / (count - 1)) for key in question.criteria
                }
                answer = Judgment(
                    question_id=question.id,
                    kind="choice",
                    source="mock",
                    choice=choice,
                    probabilities=probabilities,
                    confidence=0.4,
                )
            answers[question.id] = answer
        return BatchResult(answers, "mock-v1", 0)


class LocalJudge:
    source = "local"

    async def evaluate(self, state: dict, questions: list[Question]) -> BatchResult:
        return BatchResult()


class JevJudge:
    source = "jev"

    def __init__(self, settings: Settings, client_factory=None):
        self.settings = settings
        self.client_factory = client_factory
        self._semaphore = asyncio.Semaphore(settings.concurrency)

    async def evaluate(self, state: dict, questions: list[Question]) -> BatchResult:
        if not questions:
            return BatchResult()
        if self.client_factory is None and not os.getenv("TYPESAFE_API_KEY"):
            raise ProviderError("missing_api_key")
        from typesafe_sdk import AsyncTypeSafeClient, Choice, Noul, RetryPolicy

        factory = self.client_factory or AsyncTypeSafeClient
        batches = [
            questions[i : i + self.settings.batch_size]
            for i in range(0, len(questions), self.settings.batch_size)
        ]
        try:
            # Explicit timeout bounds all chunks plus SDK retries, not just each HTTP request.
            async with asyncio.timeout(self.settings.timeout_seconds):
                async with factory(
                    model=self.settings.model,
                    timeout=self.settings.timeout_seconds,
                    retry=RetryPolicy(max_retries=1),
                ) as client:

                    async def run(batch):
                        compiled = {
                            q.id: Noul(instructions=q.instructions)
                            if q.kind == "noul"
                            else Choice(instructions=q.instructions, criteria=q.criteria)
                            for q in batch
                        }
                        async with self._semaphore:
                            response = await client.system_one(
                                state=state, questions=compiled, model=self.settings.model
                            )
                        if response.model != self.settings.model:
                            raise ProviderError("unexpected_model_version")
                        parsed = {}
                        for q in batch:
                            answer = response.answers[q.id]
                            if q.kind == "noul":
                                p = answer.noul
                                if not math.isfinite(p) or not 0 <= p <= 1:
                                    raise ProviderError("invalid_noul")
                                parsed[q.id] = Judgment(
                                    question_id=q.id, kind="noul", source="jev", noul=p
                                )
                            else:
                                probs = dict(answer.probabilities)
                                if (
                                    set(probs) != set(q.criteria)
                                    or any(
                                        not math.isfinite(p) or not 0 <= p <= 1
                                        for p in probs.values()
                                    )
                                    or abs(sum(probs.values()) - 1) > 0.02
                                    or answer.choice not in probs
                                    or probs.get(answer.choice, -1) < max(probs.values(), default=0)
                                ):
                                    raise ProviderError("invalid_choice_distribution")
                                parsed[q.id] = Judgment(
                                    question_id=q.id,
                                    kind="choice",
                                    source="jev",
                                    choice=answer.choice,
                                    probabilities=probs,
                                    confidence=answer.confidence,
                                )
                        return parsed, response.usage

                    # TaskGroup cancels sibling requests if any chunk fails: no orphan API calls.
                    async with asyncio.TaskGroup() as group:
                        jobs = [group.create_task(run(batch)) for batch in batches]
                    answers, usage = {}, {"input_tokens": 0, "output_tokens": 0}
                    for job in jobs:
                        parsed, tokens = job.result()
                        answers.update(parsed)
                        for key in usage:
                            usage[key] += getattr(tokens, key, 0) or 0
                    return BatchResult(answers, self.settings.model, len(batches), usage)
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 - isolate and sanitize the external SDK boundary
            # Error class is enough to debug routing; error text may contain sensitive data.
            raise ProviderError(f"upstream_{type(exc).__name__}") from None


def make_judge(settings: Settings) -> Judge:
    if settings.backend == "jev":
        return JevJudge(settings)
    return MockJudge() if settings.backend == "mock" else LocalJudge()
