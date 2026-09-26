import asyncio
import json

import httpx2
import pytest
from typesafe_sdk import AsyncTypeSafeClient

from jev_chinesener.config import Settings
from jev_chinesener.models import SegmentRequest
from jev_chinesener.providers import JevJudge, ProviderError
from jev_chinesener.questions import Question, boundary_questions
from jev_chinesener.service import Segmenter, validate_partition


def factory_with(handler):
    return lambda **kwargs: AsyncTypeSafeClient(
        api_key="test-only-placeholder", transport=httpx2.MockTransport(handler), **kwargs
    )


def response_for(payload):
    answers = {}
    for key, question in payload["questions"].items():
        if question["type"] == "noul":
            answers[key] = {"type": "noul", "noul": 0.7}
        else:
            options = list(question["criteria"])
            answers[key] = {
                "type": "choice",
                "choice": options[0],
                "confidence": 0.8,
                "probabilities": {k: int(k == options[0]) for k in options},
            }
    return {
        "model": "jev-1.13.0",
        "answers": answers,
        "usage": {"input_tokens": 30, "output_tokens": 5},
    }


async def test_real_sdk_wire_contract_fixed_model_and_parallel_batches():
    received = []
    active = peak = 0

    async def handler(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        payload = json.loads(request.content)
        assert request.url.path == "/v1/systemone"
        assert payload["model"] == "jev-1.13.0"
        received.append(payload)
        active -= 1
        return httpx2.Response(200, json=response_for(payload))

    judge = JevJudge(Settings(batch_size=2, concurrency=2), factory_with(handler))
    questions = boundary_questions("南京市长江大桥") + [
        Question(
            id="role",
            kind="choice",
            instructions={"question": "候选角色"},
            criteria={"proper_name": "专名", "unknown": "不确定"},
        )
    ]
    result = await judge.evaluate({"source_text": "南京市长江大桥"}, questions)
    assert len(result.answers) == len(questions)
    assert 1 < peak <= 2
    assert result.requests == 4
    assert result.usage["input_tokens"] == 120
    assert result.answers["role"].choice == "proper_name"
    assert all(len(batch["questions"]) <= 2 for batch in received)


@pytest.mark.parametrize("corruption", ["model", "missing", "probability", "choice", "argmax"])
async def test_bad_upstream_responses_are_rejected(corruption):
    def handler(request):
        payload = json.loads(request.content)
        response = response_for(payload)
        if corruption == "model":
            response["model"] = "jev-latest"
        elif corruption == "missing":
            response["answers"] = {}
        elif corruption == "probability":
            response["answers"]["unit:cut:1"]["noul"] = 1.5
        elif corruption == "argmax":
            response["answers"]["type"]["choice"] = "not_entity"
        else:
            response["answers"]["type"]["probabilities"] = {"unknown": 0.2}
        return httpx2.Response(200, json=response)

    judge = JevJudge(Settings(), factory_with(handler))
    questions = boundary_questions("甲乙") + [
        Question(
            id="type",
            kind="choice",
            instructions={"question": "类型"},
            criteria={"unknown": "不确定", "not_entity": "非实体"},
        )
    ]
    with pytest.raises(ProviderError):
        await judge.evaluate({}, questions)


async def test_timeout_and_cancellation_leave_no_pending_calls():
    active = 0

    async def handler(request):
        nonlocal active
        active += 1
        try:
            await asyncio.sleep(1)
        finally:
            active -= 1
        return httpx2.Response(500)

    judge = JevJudge(Settings(timeout_seconds=0.02, batch_size=1), factory_with(handler))
    with pytest.raises(ProviderError):
        await judge.evaluate({}, boundary_questions("甲乙丙丁戊"))
    assert active == 0


def test_production_model_cannot_silently_follow_alias():
    with pytest.raises(ValueError):
        Settings(model="jev-latest")
    settings = Settings()
    with pytest.raises(ValueError):
        settings.model = "jev-latest"


async def test_two_rounds_use_decoded_parent_and_keep_raw_probabilities():
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        response = response_for(payload)
        assert payload["state"]["region_context"] == "江苏省"
        for key, question in payload["questions"].items():
            answer = response["answers"][key]
            if question["type"] == "noul":
                answer["noul"] = (
                    0.99 if key.startswith("component:") and key.endswith(":2") else 0.01
                )
            else:
                candidate = question["instructions"].get("candidate")
                if ":role:" in key:
                    choice = {"星海": "proper_name", "路": "generic"}.get(candidate, "unknown")
                elif key == "plan":
                    choice = "unknown"
                else:
                    choice = "road" if candidate == "星海路" else "unknown"
                answer["choice"] = choice
                answer["probabilities"] = {k: int(k == choice) for k in question["criteria"]}
        return httpx2.Response(200, json=response)

    settings = Settings(backend="jev", batch_size=64)
    result = await Segmenter(settings, JevJudge(settings, factory_with(handler))).segment(
        SegmentRequest(text="星海路", region_context="江苏省", top_k=1)
    )
    assert result.diagnostics["rounds"] == 2
    assert result.units[0].text == "星海路"
    assert [(c.text, c.role) for c in result.units[0].components] == [
        ("星海", "proper_name"),
        ("路", "generic"),
    ]
    assert result.raw_model_probabilities and not result.mock_judgments
    assert result.calibrated_acceptance_score is None
    assert any(q.startswith("component:") for p in calls for q in p["questions"])
    validate_partition(result.text, result.units, True)
