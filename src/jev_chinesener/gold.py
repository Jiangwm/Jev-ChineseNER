from typing import Literal

from pydantic import BaseModel, Field, NonNegativeInt, PositiveInt, model_validator

from .models import EntityType, Role

GoldSpan = tuple[NonNegativeInt, PositiveInt]


class GoldComponent(BaseModel):
    span: GoldSpan
    role: Role


class GoldUnit(BaseModel):
    span: GoldSpan
    entity_type: EntityType
    components: list[GoldComponent] = Field(min_length=1)
    oov: bool = False


class GoldDocument(BaseModel):
    id: str
    text: str = Field(min_length=1, max_length=128)
    input_kind: Literal["place_name", "address"]
    region_context: str | None = None
    annotation_version: str
    split: Literal["demo", "train", "dev", "test"]
    place_groups: list[str] = Field(default_factory=list)
    units: list[GoldUnit] = Field(min_length=1)
    notes: str = ""

    @model_validator(mode="after")
    def coverage(self):
        if self.split != "demo" and not self.place_groups:
            raise ValueError("formal gold requires canonical place_groups for split isolation")
        cursor = 0
        for unit in self.units:
            start, end = unit.span
            if start != cursor or not start < end <= len(self.text):
                raise ValueError("gold units must partition original text")
            child = start
            for part in unit.components:
                a, b = part.span
                if a != child or not a < b <= end:
                    raise ValueError("gold component must be nonempty and inside parent")
                child = b
            if child != end:
                raise ValueError("gold components must cover their parent")
            cursor = end
        if cursor != len(self.text):
            raise ValueError("gold units must cover original text")
        return self


def validate_dataset(rows: list[GoldDocument]) -> None:
    """A place/alias group may occur in only one formal train/dev/test partition."""
    if not rows or len({row.id for row in rows}) != len(rows):
        raise ValueError("gold must be nonempty with unique document IDs")
    splits: dict[str, str] = {}
    for row in rows:
        if row.split == "demo":
            continue
        for group in row.place_groups:
            if not group.strip():
                raise ValueError("place group must be nonempty")
            if group in splits and splits[group] != row.split:
                raise ValueError("place group leaks across train/dev/test splits")
            splits[group] = row.split
