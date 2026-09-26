import pytest

from jev_chinesener.evaluation import component_metrics, evaluate, prf, probability_metrics
from jev_chinesener.gold import GoldDocument, validate_dataset


def test_metrics_known_values():
    assert prf(1, 2, 4) == {"precision": 0.5, "recall": 0.25, "f1": 1 / 3}
    metrics = probability_metrics([(0, 0), (1, 1)])
    assert metrics["brier"] == 0 and metrics["ece_10_bins"] == 0
    assert len(metrics["reliability_curve"]) == 2
    assert probability_metrics([(0.5, 1), (0.5, 0)])["brier"] == 0.25


async def test_real_eval_must_not_report_fallback_as_jev(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    row = {
        "id": "x",
        "text": "星海路",
        "input_kind": "place_name",
        "units": [{"span": [0, 3], "entity_type": "road"}],
    }
    for route in ["hybrid_jev", "boundary_jev", "selective_jev"]:
        with pytest.raises(RuntimeError):
            await evaluate([row], route)


def test_gold_rejects_children_crossing_parent():
    with pytest.raises(ValueError):
        GoldDocument.model_validate(
            {
                "id": "bad",
                "text": "甲乙",
                "input_kind": "address",
                "annotation_version": "test",
                "split": "demo",
                "units": [
                    {
                        "span": [0, 1],
                        "entity_type": "unknown",
                        "components": [{"span": [0, 2], "role": "unknown"}],
                    }
                ],
            }
        )


async def test_selective_evaluation_reports_verified_fast_channel(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    row = {
        "id": "fast",
        "text": "东莞市",
        "input_kind": "place_name",
        "units": [{"span": [0, 3], "entity_type": "city"}],
    }
    report = await evaluate([row], "selective_jev")
    assert report["fast_path_rate"] == 1
    assert report["api_requests"] == 0
    assert report["candidate_recall"]["span"] == 1
    assert report["candidate_recall"]["gold_path_reachable_rate"] == 1


def test_component_span_and_role_macro_are_separate():
    gold = {(0, 3, 0, 2, "proper_name"), (0, 3, 2, 3, "generic")}
    predicted = {(0, 3, 0, 2, "proper_name"), (0, 3, 2, 3, "qualifier")}
    metrics = component_metrics([(predicted, gold)])
    assert metrics["span_parent"]["f1"] == 1
    assert metrics["role_macro_f1"] == pytest.approx(1 / 3)
    assert metrics["per_role"]["generic"]["recall"] == 0


def test_formal_gold_requires_groups_and_prevents_alias_leakage():
    import json
    from pathlib import Path

    row = json.loads(Path("fixtures/gold.jsonl").read_text().splitlines()[0])
    row.update(split="train", place_groups=[])
    with pytest.raises(ValueError):
        GoldDocument.model_validate(row)
    row["place_groups"] = ["canonical-nanjing"]
    train = GoldDocument.model_validate(row)
    test = GoldDocument.model_validate({**row, "id": "test-alias", "split": "test"})
    with pytest.raises(ValueError, match="leaks"):
        validate_dataset([train, test])


async def test_jieba_lexicon_baseline_keeps_full_road():
    row = {
        "id": "road",
        "text": "上海市南京东路",
        "input_kind": "address",
        "units": [{"span": [0, 3], "entity_type": "city"}, {"span": [3, 7], "entity_type": "road"}],
    }
    report = await evaluate([row], "jieba_lexicon")
    assert report["exact_match"] == 1 and report["api_requests"] == 0
