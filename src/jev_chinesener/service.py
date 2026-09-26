import json
import time
import unicodedata
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files

from .cache import PROCESS_LIMITS, ProcessLimits, ResponseCache, fingerprint, response_key
from .candidates import RULE_VERSION, build_graph, rules
from .components import compile_components, component_graph, resolve_components
from .config import Settings
from .decoder import Path, decode
from .lexicon import LEXICON_VERSION, Lexicon
from .models import Component, Evidence, Hypothesis, SegmentRequest, SegmentResponse, Span, Unit
from .providers import BatchResult, Judge, ProviderError, make_judge
from .questions import PROMPT_VERSION, Question, first_round

BOUNDARY_CALIBRATION_VERSION = "identity-not-fitted-v1"


class UnsupportedScope(ValueError):
    pass


class Segmenter:
    def __init__(
        self,
        settings: Settings | None = None,
        judge: Judge | None = None,
        lexicon: Lexicon | None = None,
        limits: ProcessLimits | None = None,
    ):
        self.settings = settings or Settings.from_env()
        self.judge = judge or make_judge(self.settings)
        self.lexicon = lexicon or Lexicon()
        self.limits = limits if limits is not None else PROCESS_LIMITS
        self.cache: ResponseCache | None = None
        self._cache_judge = self.judge
        self.verified = json.loads(
            files("jev_chinesener.data").joinpath("verified_inputs.json").read_text()
        )

    def versions(self, actual_model: str | None = None) -> dict[str, str | None]:
        # 响应与缓存键共用版本清单，避免两份版本来源漂移。
        return {
            "lexicon": LEXICON_VERSION,
            "lexicon_fingerprint": self.lexicon.fingerprint,
            "rules": RULE_VERSION,
            "annotation_standard": "annotation-0.1.0",
            "prompt": PROMPT_VERSION,
            "model_requested": self.settings.model,
            "model_used": actual_model,
            "calibration": "not_fitted",
            "boundary_calibration": BOUNDARY_CALIBRATION_VERSION,
            "normalization": "NFKC-display-only-v1",
            "local_tokenizer": "jieba-0.42.1",
            "fast_path": "fast-0.2.0",
        }

    def cache_key(self, request: SegmentRequest) -> str:
        versions = {
            **self.versions(),
            "rules_fingerprint": fingerprint(rules()),
            "verified_inputs_fingerprint": fingerprint(self.verified),
            # 词条有效期会在 UTC 日期变化时改变匹配，即使内容未变也须 miss。
            "lexicon_as_of": datetime.now(UTC).date().isoformat(),
        }
        return response_key(request, self.settings, versions, self.judge.source)

    def prepare(self, request: SegmentRequest):
        if request.input_kind == "text":
            raise UnsupportedScope("篇章 text NER 为后续扩展；阶段一仅支持 place_name 和 address")
        edges = build_graph(request.text, self.lexicon, self.settings.max_candidate_length)
        state, questions = first_round(request, edges)
        return edges, state, questions

    def fast_route(self, request, edges) -> Path | None:
        if not self.settings.fast_path or request.region_context:
            return None
        record = next(
            (
                row
                for row in self.verified
                if row["text"] == request.text
                and request.input_kind in row.get("input_kinds", [])
                and row.get("lexicon_fingerprint") == self.lexicon.fingerprint
            ),
            None,
        )
        if not record:
            return None
        path, start = [], 0
        for word in record["units"]:
            edge = next(
                (
                    e
                    for e in edges
                    if e.start == start
                    and e.text == word
                    and e.entry
                    and e.entry.canonical_name == word
                    and e.entry.verified_components
                ),
                None,
            )
            if edge is None:
                return None
            path.append(edge)
            start += len(word)
        return (
            Path(sum(e.feature_score for e in path), path) if start == len(request.text) else None
        )

    def render(self, path: Path, prefix: str, components: bool, type_answers: dict) -> Hypothesis:
        units = []
        for i, edge in enumerate(path.edges):
            answer = type_answers.get(edge.key)
            kind = edge.entity_type
            if answer and answer.choice:
                # Choice may reject morphology or disambiguate organization/place evidence.
                kind = answer.choice
            unit_id = f"{prefix}u{i}"
            evidence = [
                Evidence(source=source, version=edge.entry.version if edge.entry else RULE_VERSION)
                for source in sorted(edge.sources)
            ]
            if answer:
                evidence.append(
                    Evidence(
                        source=answer.source, version=PROMPT_VERSION, detail=answer.question_id
                    )
                )
            unit = Unit(
                id=unit_id,
                text=edge.text,
                span=Span(start=edge.start, end=edge.end),
                entity_type=kind,
                normalized_name=edge.entry.canonical_name
                if edge.entry
                else unicodedata.normalize("NFKC", edge.text),
                lexicon_entity_id=edge.entry.entity_id if edge.entry else None,
                evidence=evidence,
            )
            if components:
                if (
                    edge.entry
                    and edge.text == edge.entry.canonical_name
                    and kind == edge.entry.entity_type
                ):
                    unit.components = [
                        Component(
                            id=f"{unit_id}:c{j}",
                            parent_id=unit_id,
                            text=part.text,
                            span=Span(
                                start=edge.start + part.span.start, end=edge.start + part.span.end
                            ),
                            role=part.role,
                            evidence=[
                                Evidence(source="verified_components", version=edge.entry.version)
                            ],
                        )
                        for j, part in enumerate(edge.entry.verified_components)
                    ]
                elif kind in {"separator", "house_number", "not_entity"}:
                    unit.components = [
                        Component(
                            id=f"{unit_id}:c0",
                            parent_id=unit_id,
                            text=unit.text,
                            span=unit.span,
                            role="number" if kind == "house_number" else "not_entity",
                            evidence=evidence,
                        )
                    ]
            units.append(unit)
        return Hypothesis(score=path.score, units=units)

    async def segment(self, request: SegmentRequest) -> SegmentResponse:
        if request.input_kind == "text":
            raise UnsupportedScope("篇章 text NER 为后续扩展；阶段一仅支持 place_name 和 address")
        self.limits.admit(self.settings)
        cache = None
        started = time.perf_counter()
        if self.settings.cache_enabled:
            if (
                self.cache is None
                or self.cache.max_entries != self.settings.cache_max_entries
                or self.cache.ttl_seconds != self.settings.cache_ttl_seconds
                or self._cache_judge is not self.judge
            ):
                self.cache = ResponseCache(
                    self.settings.cache_max_entries, self.settings.cache_ttl_seconds
                )
                self._cache_judge = self.judge
            cache = self.cache
            key = self.cache_key(request)
            cached = cache.get(key)
            if cached is not None:
                # 保留生成时的观测来源，本次调用量归零，避免重复累计 token/请求。
                cached.diagnostics["cache_origin"] = {
                    name: cached.diagnostics[name]
                    for name in ("rounds", "api_requests", "questions", "usage", "elapsed_ms")
                }
                cached.diagnostics.update(
                    cache_hit=True,
                    rounds=0,
                    api_requests=0,
                    questions=0,
                    usage={},
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                )
                return cached
        response, cacheable = await self._segment_uncached(request)
        if cache is not None:
            response.diagnostics["cache_hit"] = False
            # 上游失败不缓存；请求途中配置/资产发生变化也不存入旧键。
            if cacheable and self._cache_judge is self.judge and key == self.cache_key(request):
                cache.put(key, response)
        return response

    async def _segment_uncached(self, request: SegmentRequest) -> tuple[SegmentResponse, bool]:
        started = time.perf_counter()
        edges, state, questions = self.prepare(request)
        fast = self.fast_route(request, edges)
        warnings, answers, usage = [], {}, {}
        rounds = requests = question_count = 0
        actual_model = None
        failed = False

        async def evaluate(batch):
            nonlocal rounds, requests, question_count, actual_model, failed
            if not batch:
                return {}
            rounds += 1
            question_count += len(batch)
            try:
                result: BatchResult = await self.judge.evaluate(state, batch)
                answers.update(result.answers)
                requests += result.requests
                actual_model = result.model or actual_model
                for key, value in result.usage.items():
                    usage[key] = usage.get(key, 0) + value
                return result.answers
            except ProviderError as exc:
                failed = True
                warnings.append(f"Jev 不可用，回退本地词图：{exc}")
                return {}

        type_answers = {}
        if fast:
            paths = [fast]
        else:
            first = await evaluate(questions)
            cuts = {
                q.gap: first[q.id].noul for q in questions if q.kind == "noul" and q.id in first
            }
            type_answers = {
                q.edge_key: first[q.id] for q in questions if q.kind == "choice" and q.id in first
            }
            # Copy before assigning candidate types so the lexical asset remains unchanged.
            paths = decode(
                len(request.text),
                [replace(e) for e in edges],
                cuts,
                type_answers,
                top_k=max(2, request.top_k),
            )

        want_components = request.return_components or request.granularity in {
            "name_component",
            "both",
        }
        hypotheses = [
            self.render(path, f"h{i}:", want_components, type_answers)
            for i, path in enumerate(paths)
        ]
        margin = paths[0].score - paths[1].score if len(paths) > 1 else None
        close = margin is not None and margin < self.settings.ambiguity_margin
        second, pending = [], []
        if want_components:
            for hypothesis in hypotheses:
                for unit in hypothesis.units:
                    if not unit.components:
                        graph = component_graph(unit)
                        pending.append((unit, graph))
                        second.extend(compile_components(unit, graph))

        if close and not fast:
            options = {
                f"path{i}": [
                    {"text": u.text, "entity_type": u.entity_type} for u in hypothesis.units
                ]
                for i, hypothesis in enumerate(hypotheses)
            }
            options.update(unknown="证据不足，不能选择", not_entity="不是地名或地址")
            second.append(
                Question(
                    id="plan",
                    kind="choice",
                    instructions={
                        "question": "哪一个候选方案最符合完整地理单元粒度？",
                        "policy": "只在已覆盖原文的合法方案中选择；保留名称内部完整性。",
                    },
                    criteria=options,
                )
            )
        second_answers = await evaluate(second) if not failed and not fast else {}
        for unit, graph in pending:
            resolve_components(unit, graph, second_answers)

        # A local plan Choice only selects an existing legal path; it never creates spans.
        plan = second_answers.get("plan")
        selected_path = paths[0]
        if plan and plan.choice and plan.choice.startswith("path"):
            index = int(plan.choice[4:])
            hypotheses.insert(0, hypotheses.pop(index))
            selected_path = paths[index]
        selected = hypotheses[0]
        uncertain = any(u.entity_type == "unknown" for u in selected.units)
        uncertain_components = want_components and any(
            c.role == "unknown" for u in selected.units for c in u.components
        )
        # Budgeted shortlisting must not turn an unreviewed lexical guess into model acceptance.
        unreviewed = not fast and any(
            len(e.text) > 1 and e.entity_type != "separator" and e.key not in type_answers
            for e in selected_path.edges
        )
        ambiguous = (
            close
            or uncertain
            or uncertain_components
            or unreviewed
            or bool(plan and plan.choice in {"unknown", "not_entity"})
        )
        degraded = failed or (not fast and self.judge.source in {"mock", "local"})
        if not fast and self.judge.source == "mock":
            warnings.append("mock 仅验证工程流程；合成概率不是 Jev 的测量结果。")
        if not fast and self.judge.source == "local":
            warnings.append("本地候选与规则回退；未经验证的部分不视为已接受结果。")
        if any(u.entity_type == "organization" for u in selected.units):
            warnings.append("机构名不等于具体物理场所；南京大学需校区或场所语境才能判为 poi。")
        for hypothesis in hypotheses:
            for unit in hypothesis.units:
                if fast:
                    unit.evidence.append(Evidence(source="verified_input", version="fast-0.2.0"))
                for gap in range(
                    unit.span.start + 1, min(unit.span.end, len(request.text) - 1) + 1
                ):
                    judgment = answers.get(f"unit:cut:{gap}")
                    if judgment:
                        unit.evidence.append(
                            Evidence(
                                source=f"{judgment.source}_boundary",
                                version=PROMPT_VERSION,
                                detail=judgment.question_id,
                            )
                        )
            validate_partition(request.text, hypothesis.units, want_components)
        raw = [a for a in answers.values() if a.source == "jev"]
        mocked = [a for a in answers.values() if a.source == "mock"]
        response = SegmentResponse(
            text=request.text,
            input_kind=request.input_kind,
            granularity=request.granularity,
            status="degraded" if degraded else "ambiguous" if ambiguous else "ok",
            units=selected.units,
            alternatives=hypotheses[1 : request.top_k],
            ambiguity={
                "detected": ambiguous,
                "score_margin": margin,
                "margin_threshold": self.settings.ambiguity_margin,
                "threshold_validated": False,
                "plan_choice": plan.choice if plan else None,
                "unknown_unit": uncertain,
                "unknown_component": uncertain_components,
                "unreviewed_unit_type": bool(unreviewed),
                "ranking_score_is_probability": False,
            },
            raw_model_probabilities=raw,
            mock_judgments=mocked,
            versions=self.versions(actual_model),
            diagnostics={
                "fast_path": fast is not None,
                "backend": self.judge.source,
                "rounds": rounds,
                "api_requests": requests,
                "questions": question_count,
                "candidate_count": len(edges),
                "usage": usage,
                "elapsed_ms": (time.perf_counter() - started) * 1000,
                "chinese_validation": "not_run",
            },
            warnings=warnings,
        )
        return response, not failed


def validate_partition(text: str, units: list[Unit], require_components: bool):
    cursor = 0
    ids = set()
    for unit in units:
        if (
            unit.id in ids
            or unit.span.start != cursor
            or not cursor < unit.span.end <= len(text)
            or text[cursor : unit.span.end] != unit.text
        ):
            raise ValueError("unit coverage or source fidelity violation")
        ids.add(unit.id)
        cursor = unit.span.end
        child_cursor = unit.span.start
        for part in unit.components:
            if (
                part.id in ids
                or part.parent_id != unit.id
                or part.span.start != child_cursor
                or not child_cursor < part.span.end <= unit.span.end
                or text[part.span.start : part.span.end] != part.text
            ):
                raise ValueError("component escaped parent or lost source fidelity")
            ids.add(part.id)
            child_cursor = part.span.end
        if (require_components or unit.components) and child_cursor != unit.span.end:
            raise ValueError("component coverage violation")
    if cursor != len(text):
        raise ValueError("source not fully covered")
