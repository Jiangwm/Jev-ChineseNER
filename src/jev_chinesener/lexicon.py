import hashlib
import json
from datetime import UTC, date, datetime
from importlib.resources import files
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from .models import EntityType, Role, Span

LEXICON_VERSION = "demo-2026.09.20"


class VerifiedComponent(BaseModel):
    text: str
    role: Role
    span: Span


class ParentRelation(BaseModel):
    entity_id: str
    relation: Literal["administrative_parent", "located_in"]


class LexiconEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    canonical_name: str
    aliases: list[str]
    entity_type: EntityType
    parent_relations: list[ParentRelation]
    verified_components: list[VerifiedComponent]
    valid_from: date | None
    valid_to: date | None
    source: str
    version: str

    @model_validator(mode="after")
    def valid_components(self):
        cursor = 0
        for part in self.verified_components:
            if (
                part.span.start != cursor
                or self.canonical_name[cursor : part.span.end] != part.text
            ):
                raise ValueError("verified components must partition the canonical name")
            cursor = part.span.end
        if self.verified_components and cursor != len(self.canonical_name):
            raise ValueError("incomplete verified components")
        if self.valid_from and self.valid_to and self.valid_from > self.valid_to:
            raise ValueError("invalid validity interval")
        if not self.canonical_name or any(not alias for alias in self.aliases):
            raise ValueError("empty lexicon surface")
        return self


class Lexicon:
    """Trie over original surfaces. IDs are lexical evidence, never resolved entities."""

    def __init__(self, entries: list[LexiconEntry] | None = None):
        if entries is None:
            data = json.loads(files("jev_chinesener.data").joinpath("lexicon.json").read_text())
            entries = [LexiconEntry.model_validate(row) for row in data]
        self.entries = entries
        self.trie: dict = {}
        ids = [entry.entity_id for entry in entries]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate lexicon IDs")
        for entry in entries:
            for name in [entry.canonical_name, *entry.aliases]:
                node = self.trie
                for char in name:
                    node = node.setdefault(char, {})
                node.setdefault(None, []).append(entry)

    @property
    def fingerprint(self) -> str:
        # 实时反映已加载词条内容；更换名称/别名时仍须重建 Lexicon 以同步 Trie。
        payload = [
            entry.model_dump(mode="json")
            for entry in sorted(self.entries, key=lambda e: e.entity_id)
        ]
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def matches(self, text: str, as_of: date | None = None):
        as_of = as_of or datetime.now(UTC).date()
        for start in range(len(text)):
            node = self.trie
            for end in range(start, len(text)):
                node = node.get(text[end])
                if node is None:
                    break
                for entry in node.get(None, []):
                    if (entry.valid_from is None or entry.valid_from <= as_of) and (
                        entry.valid_to is None or as_of <= entry.valid_to
                    ):
                        yield start, end + 1, entry
