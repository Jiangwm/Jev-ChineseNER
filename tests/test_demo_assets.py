"""Offline asset/regression checks, not independent Chinese model validation."""

import json
from pathlib import Path

import pytest

from jev_chinesener.config import Settings
from jev_chinesener.gold import GoldDocument, validate_dataset
from jev_chinesener.lexicon import Lexicon, LexiconEntry
from jev_chinesener.models import SegmentRequest
from jev_chinesener.service import Segmenter, validate_partition

GOLD = [
    GoldDocument.model_validate_json(line)
    for line in Path("fixtures/gold.jsonl").read_text().splitlines()
]
NEW_GOLD_IDS = {
    "xiamen-organization-address",
    "ningxia-address",
    "guangzhou-borrowed-city-road",
    "southeast-university",
    "zhejiang-hangzhou",
    "ningxia-components",
    "beijing-road",
    "xiamen-alias",
}
COUNTEREXAMPLES = json.loads(Path("fixtures/counterexamples.json").read_text())
EXECUTABLE_CASES = [row for row in COUNTEREXAMPLES if "assertions" in row]


def test_demo_assets_load_and_match_documented_schemas():
    lexicon = Lexicon()
    assert len(lexicon.entries) >= 36
    assert len(GOLD) >= 20 and len(COUNTEREXAMPLES) >= 15
    assert len(EXECUTABLE_CASES) >= 5
    assert NEW_GOLD_IDS <= {row.id for row in GOLD}
    assert all(row.split == "demo" and row.place_groups for row in GOLD)
    validate_dataset(GOLD)
    assert LexiconEntry.model_json_schema() == json.loads(
        Path("docs/lexicon.schema.json").read_text()
    )
    assert GoldDocument.model_json_schema() == json.loads(Path("docs/gold.schema.json").read_text())
    ids = {entry.entity_id for entry in lexicon.entries}
    for entry in lexicon.entries:
        assert all(parent.entity_id in ids for parent in entry.parent_relations)
        for surface in [entry.canonical_name, *entry.aliases]:
            assert any(
                start == 0 and end == len(surface) and match.entity_id == entry.entity_id
                for start, end, match in lexicon.matches(surface)
            )


def test_extended_lexicon_invalidates_original_asset_fingerprint():
    lexicon = Lexicon()
    original = Lexicon([e for e in lexicon.entries if e.version == "demo-2026.09.20"])
    assert len(original.entries) == 24
    assert lexicon.fingerprint != original.fingerprint
    engine = Segmenter(Settings(backend="mock"))
    assert len(engine.verified) == 7  # No new input memorization for this expansion.
    for record in engine.verified:
        assert record["lexicon_fingerprint"] == lexicon.fingerprint
        for kind in record["input_kinds"]:
            request = SegmentRequest(text=record["text"], input_kind=kind)
            edges, _, _ = engine.prepare(request)
            path = engine.fast_route(request, edges)
            assert path is not None
            assert [edge.text for edge in path.edges] == record["units"]
        record["lexicon_fingerprint"] = original.fingerprint
        assert engine.fast_route(request, edges) is None


def test_new_alias_keeps_canonical_place_group_for_formal_split_checks():
    canonical = next(row for row in GOLD if row.id == "xiamen-organization-address")
    alias = next(row for row in GOLD if row.id == "xiamen-alias")
    assert "demo:xm" in canonical.place_groups
    assert alias.place_groups == ["demo:xm"]
    train = GoldDocument.model_validate({**canonical.model_dump(), "split": "train"})
    test = GoldDocument.model_validate({**alias.model_dump(), "split": "test"})
    with pytest.raises(ValueError, match="leaks"):
        validate_dataset([train, test])


@pytest.mark.parametrize("row", [row for row in GOLD if row.id in NEW_GOLD_IDS], ids=lambda r: r.id)
async def test_new_gold_annotations_without_fast_path(row):
    result = await Segmenter(Settings(backend="mock", fast_path=False)).segment(
        SegmentRequest(text=row.text, input_kind=row.input_kind)
    )
    assert not result.diagnostics["fast_path"]
    assert result.diagnostics["api_requests"] == 0
    assert result.raw_model_probabilities == []
    validate_partition(row.text, result.units, True)
    assert [(u.span.start, u.span.end, u.entity_type) for u in result.units] == [
        (*u.span, u.entity_type) for u in row.units
    ]
    assert [[(c.span.start, c.span.end, c.role) for c in u.components] for u in result.units] == [
        [(*c.span, c.role) for c in u.components] for u in row.units
    ]


@pytest.mark.parametrize("backend", ["mock", "local"])
@pytest.mark.parametrize("case", EXECUTABLE_CASES, ids=lambda row: row["text"])
async def test_counterexample_assertions_without_fast_path(case, backend):
    result = await Segmenter(Settings(backend=backend, fast_path=False)).segment(
        SegmentRequest(text=case["text"], input_kind="place_name")
    )
    expected = case["assertions"]
    assert not result.diagnostics["fast_path"]
    assert result.diagnostics["api_requests"] == 0
    assert result.raw_model_probabilities == []
    validate_partition(case["text"], result.units, True)
    assert [u.text for u in result.units] == expected["units"]
    assert not set(expected["forbidden_types"]) & {u.entity_type for u in result.units}
    if "types" in expected:
        assert [u.entity_type for u in result.units] == expected["types"]
    if "components" in expected:
        assert [[[c.text, c.role] for c in u.components] for u in result.units] == expected[
            "components"
        ]
    assert all(u.linked_entity_id is None for u in result.units)
    assert all("entity_type" not in c.model_dump() for u in result.units for c in u.components)
