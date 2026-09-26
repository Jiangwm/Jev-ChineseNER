import json
import random
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jev_chinesener.api import create_app
from jev_chinesener.candidates import Edge, build_graph
from jev_chinesener.config import Settings
from jev_chinesener.decoder import decode
from jev_chinesener.lexicon import Lexicon, LexiconEntry
from jev_chinesener.models import Judgment, SegmentRequest
from jev_chinesener.providers import MockJudge, ProviderError
from jev_chinesener.questions import boundary_questions
from jev_chinesener.service import Segmenter, validate_partition


class NeverJudge:
    source = "jev"

    async def evaluate(self, state, questions):
        raise AssertionError("verified input must skip Jev")


@pytest.mark.parametrize(
    "text,words,parts",
    [
        ("南京市长江大桥", ["南京市", "长江大桥"], [["南京", "市"], ["长江", "大桥"]]),
        ("上海市南京东路", ["上海市", "南京东路"], [["上海", "市"], ["南京", "东", "路"]]),
        ("东莞市", ["东莞市"], [["东莞", "市"]]),
        ("内蒙古自治区", ["内蒙古自治区"], [["内蒙古", "自治区"]]),
        ("广西壮族自治区", ["广西壮族自治区"], [["广西", "壮族", "自治区"]]),
    ],
)
async def test_verified_regressions(text, words, parts):
    result = await Segmenter(judge=NeverJudge()).segment(SegmentRequest(text=text))
    assert result.status == "ok"
    assert [u.text for u in result.units] == words
    assert [[c.text for c in u.components] for u in result.units] == parts
    assert result.diagnostics["rounds"] == 0
    assert result.raw_model_probabilities == []
    assert result.versions["model_used"] is None
    validate_partition(text, result.units, True)


async def test_borrowed_name_is_component_not_city():
    result = await Segmenter().segment(SegmentRequest(text="上海市南京东路"))
    road = result.units[1]
    assert road.entity_type == "road"
    part = road.components[0]
    assert part.text == "南京" and part.role == "proper_name" and part.parent_id == road.id
    assert "entity_type" not in part.model_dump()


async def test_organization_place_distinction():
    engine = Segmenter()
    org = await engine.segment(SegmentRequest(text="南京大学"))
    campus = await engine.segment(SegmentRequest(text="南京大学仙林校区"))
    assert org.units[0].entity_type == "organization"
    assert campus.units[0].entity_type == "poi"
    assert org.units[0].linked_entity_id is None
    assert any("机构名" in w for w in org.warnings)


async def test_original_unicode_and_normalization_are_separate():
    text = " 南京市😀仙林大道１３８号\n"
    result = await Segmenter().segment(SegmentRequest(text=text))
    validate_partition(text, result.units, True)
    number = next(u for u in result.units if u.text == "１３８号")
    assert number.normalized_name == "138号"
    emoji = next(u for u in result.units if u.text == "😀")
    assert emoji.span.end - emoji.span.start == 1
    assert result.offset_unit == "unicode_codepoint"
    assert result.calibrated_acceptance_score is None


async def test_random_strings_lossless_at_both_levels():
    rng = random.Random(7)
    engine = Segmenter(Settings(backend="local"))
    for _ in range(35):
        text = "".join(rng.choices("南京路甲乙Ａ１😀\n \u0301", k=rng.randint(1, 18)))
        response = await engine.segment(SegmentRequest(text=text, top_k=3))
        for units in [response.units, *[h.units for h in response.alternatives]]:
            validate_partition(text, units, True)


async def test_granularity_no_flat_mixing_and_top_k():
    engine = Segmenter()
    unit = await engine.segment(
        SegmentRequest(
            text="南京长江大桥", top_k=1, granularity="geographic_unit", return_components=False
        )
    )
    assert not unit.alternatives and all(not u.components for u in unit.units)
    component = await engine.segment(
        SegmentRequest(text="东莞市", granularity="name_component", return_components=False)
    )
    assert component.units[0].components
    assert component.units[0].text == "东莞市"


async def test_mock_does_not_masquerade_as_model():
    result = await Segmenter().segment(SegmentRequest(text="星海路"))
    assert result.status == "degraded"
    assert result.mock_judgments and not result.raw_model_probabilities
    assert result.diagnostics["api_requests"] == 0
    assert result.versions["model_used"] == "mock-v1"


async def test_failure_falls_back_losslessly():
    class Broken:
        source = "jev"

        async def evaluate(self, state, questions):
            raise ProviderError("timeout")

    result = await Segmenter(judge=Broken()).segment(SegmentRequest(text="星海路１号"))
    assert result.status == "degraded"
    assert "timeout" in result.warnings[0]
    validate_partition(result.text, result.units, True)


async def test_missing_key_is_reported_without_network(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    result = await Segmenter(Settings(backend="jev")).segment(SegmentRequest(text="星海路"))
    assert result.status == "degraded"
    assert any("missing_api_key" in w for w in result.warnings)


def test_boundary_probability_changes_legal_path():
    edges = [Edge(0, 1, "甲"), Edge(1, 2, "乙"), Edge(0, 2, "甲乙")]
    assert len(decode(2, edges, {1: 0.99})[0].edges) == 2
    assert len(decode(2, edges, {1: 0.01})[0].edges) == 1
    assert len(decode(2, edges, {1: 0})[0].edges) == 1


def test_reclassified_identical_paths_are_not_false_alternatives():
    edges = [Edge(0, 2, "甲路", entity_type="road"), Edge(0, 2, "甲路")]
    judgments = {
        e.key: Judgment(
            question_id=e.key,
            kind="choice",
            source="mock",
            choice="road",
            probabilities={"road": 1},
        )
        for e in edges
    }
    assert len(decode(2, edges, {}, judgments, top_k=3)) == 1


def test_graph_fallback_and_negative_rules():
    graph = build_graph("市长😀", Lexicon())
    for i in range(3):
        assert any(e.start == i and e.end == i + 1 for e in graph)
    assert not any(e.text == "市长" and "morphology" in e.sources for e in graph)
    assert decode(3, graph, {})


async def test_reverse_order_remains_decodable():
    result = await Segmenter().segment(SegmentRequest(text="仙林大道南京市"))
    assert [u.text for u in result.units] == ["仙林大道", "南京市"]


@pytest.mark.parametrize(
    "text",
    ["南京市长江大桥", "上海市南京东路", "东莞市", "内蒙古自治区", "广西壮族自治区", "南京大学"],
)
async def test_regressions_without_fast_path(text):
    engine = Segmenter(Settings(backend="mock", fast_path=False))
    result = await engine.segment(SegmentRequest(text=text))
    expected = next(
        json.loads(line)
        for line in Path("fixtures/gold.jsonl").read_text().splitlines()
        if json.loads(line)["text"] == text
    )
    assert [u.text for u in result.units] == [
        text[u["span"][0] : u["span"][1]] for u in expected["units"]
    ]
    validate_partition(text, result.units, True)


async def test_fast_path_invalidated_by_changed_lexicon_and_scope():
    lexicon = Lexicon()
    entries = [e.model_copy(update={"verified_components": []}) for e in lexicon.entries]
    engine = Segmenter(Settings(backend="mock"), lexicon=Lexicon(entries))
    result = await engine.segment(SegmentRequest(text="东莞市"))
    assert not result.diagnostics["fast_path"] and result.status == "degraded"
    assert result.versions["lexicon_fingerprint"] != lexicon.fingerprint
    scoped = await Segmenter().segment(
        SegmentRequest(text="上海市南京东路", input_kind="place_name")
    )
    assert not scoped.diagnostics["fast_path"]


async def test_dictionary_type_can_be_rejected_without_verified_component_leak():
    class RejectEntity(MockJudge):
        async def evaluate(self, state, questions):
            result = await super().evaluate(state, questions)
            for q in questions:
                if q.id.startswith("type:"):
                    answer = result.answers[q.id]
                    answer.choice = "not_entity"
                    answer.probabilities = {key: float(key == "not_entity") for key in q.criteria}
            return result

    result = await Segmenter(Settings(fast_path=False), judge=RejectEntity()).segment(
        SegmentRequest(text="东莞市")
    )
    assert result.units[0].entity_type == "not_entity"
    assert [(c.text, c.role) for c in result.units[0].components] == [("东莞市", "not_entity")]
    assert not any(
        e.source == "verified_components" for c in result.units[0].components for e in c.evidence
    )


async def test_partial_optional_components_and_duplicate_ids_are_invalid():
    result = await Segmenter().segment(SegmentRequest(text="上海市南京东路"))
    result.units[1].id = result.units[0].id
    with pytest.raises(ValueError):
        validate_partition(result.text, result.units, True)
    result = await Segmenter().segment(SegmentRequest(text="东莞市"))
    result.units[0].components.pop()
    with pytest.raises(ValueError):
        validate_partition(result.text, result.units, False)


def test_every_gap_has_explicit_marker():
    text = "南京😀路"
    questions = boundary_questions(text)
    assert len(questions) == len(text) - 1
    for gap, q in enumerate(questions, 1):
        assert q.instructions["marked_text"] == text[:gap] + "⟦CUT⟧" + text[gap:]


def test_component_boundary_policy_does_not_prohibit_internal_splitting():
    unit = boundary_questions("星海路")[0]
    component = boundary_questions("星海路", component=True)[0]
    assert "地理单元内部不拆" in unit.instructions["policy"]
    assert "地理单元内部不拆" not in component.instructions["policy"]
    assert "允许拆开" in component.instructions["policy"]


def test_literal_marker_is_unambiguous():
    assert all(
        q.instructions["marked_text"].count("⟦CUT⟧") == 1 for q in boundary_questions("甲⟦CUT⟧乙")
    )


def test_alias_matching_and_validity():
    lexicon = Lexicon()
    assert any(entry.canonical_name == "南京市" for _, _, entry in lexicon.matches("南京"))
    entry = lexicon.entries[0].model_copy(
        update={"valid_to": __import__("datetime").date(1900, 1, 1)}
    )
    assert not list(Lexicon([entry]).matches(entry.canonical_name))
    data = lexicon.entries[0].model_dump(mode="json")
    data["verified_components"][0]["span"]["end"] = 1
    with pytest.raises(ValueError):
        LexiconEntry.model_validate(data)


def test_api_contract_and_rejected_out_of_scope():
    client = TestClient(create_app(Segmenter(Settings(backend="mock"))))
    response = client.post("/v1/toponyms/segment", json={"text": "东莞市"})
    assert response.status_code == 200
    assert response.json()["units"][0]["span"] == {"start": 0, "end": 3}
    for data in [
        {"text": ""},
        {"text": "甲" * 129},
        {"text": "甲", "top_k": 0},
        {"text": "甲", "entity_linking": True},
        {"text": "甲", "granularity": "flat"},
    ]:
        assert client.post("/v1/toponyms/segment", json=data).status_code == 422
    response = client.post("/v1/toponyms/segment", json={"text": "我去南京", "input_kind": "text"})
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_scope"


def test_gold_samples_have_lossless_nested_annotations():
    for line in Path("fixtures/gold.jsonl").read_text().splitlines():
        row = json.loads(line)
        pos = 0
        for unit in row["units"]:
            start, end = unit["span"]
            assert start == pos and end > start
            child = start
            for part in unit["components"]:
                assert part["span"][0] == child
                child = part["span"][1]
            assert child == end
            pos = end
        assert pos == len(row["text"])
