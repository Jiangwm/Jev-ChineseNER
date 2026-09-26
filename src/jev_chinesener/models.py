from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

EntityType = Literal[
    "province",
    "city",
    "district",
    "town",
    "village",
    "road",
    "bridge",
    "water",
    "mountain",
    "poi",
    "organization",
    "house_number",
    "separator",
    "unknown",
    "not_entity",
]
Role = Literal["proper_name", "generic", "qualifier", "number", "unknown", "not_entity"]


class SegmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=128)
    input_kind: Literal["place_name", "address", "text"] = "address"
    granularity: Literal["geographic_unit", "name_component", "both"] = "both"
    return_components: bool = True
    top_k: int = Field(default=3, ge=1, le=5)
    region_context: str | None = Field(default=None, max_length=256)
    entity_linking: Literal[False] = False


class Span(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        if self.end <= self.start:
            raise ValueError("span must be nonempty and half-open")
        return self


class Evidence(BaseModel):
    source: str
    version: str
    detail: str | None = None


class Component(BaseModel):
    id: str
    parent_id: str
    text: str
    span: Span
    role: Role
    evidence: list[Evidence]


class Unit(BaseModel):
    id: str
    text: str
    span: Span
    entity_type: EntityType
    normalized_name: str | None = None
    lexicon_entity_id: str | None = None
    linked_entity_id: None = None
    components: list[Component] = Field(default_factory=list)
    evidence: list[Evidence]


class Hypothesis(BaseModel):
    score: float
    units: list[Unit]


class Judgment(BaseModel):
    question_id: str
    kind: Literal["noul", "choice"]
    source: Literal["jev", "mock"]
    noul: float | None = Field(default=None, ge=0, le=1)
    choice: str | None = None
    probabilities: dict[str, float] | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)


class SegmentResponse(BaseModel):
    text: str
    input_kind: str
    granularity: str
    offset_unit: Literal["unicode_codepoint"] = "unicode_codepoint"
    span_convention: Literal["[start,end)"] = "[start,end)"
    status: Literal["ok", "ambiguous", "degraded"]
    units: list[Unit]
    alternatives: list[Hypothesis]
    ambiguity: dict
    raw_model_probabilities: list[Judgment]
    mock_judgments: list[Judgment]
    calibrated_acceptance_score: float | None = None
    calibration_status: Literal["not_fitted"] = "not_fitted"
    versions: dict[str, str | None]
    diagnostics: dict
    warnings: list[str]
    entity_linking: Literal[False] = False
