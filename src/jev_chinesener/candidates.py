import json
import re
from dataclasses import dataclass, field
from functools import cache
from importlib.resources import files

import jieba

from .lexicon import Lexicon, LexiconEntry
from .models import EntityType

RULE_VERSION = "rules-0.1.0"
_TOKENIZER = jieba.Tokenizer()
jieba.setLogLevel(30)


@dataclass
class Edge:
    start: int
    end: int
    text: str
    entity_type: EntityType = "unknown"
    sources: set[str] = field(default_factory=set)
    entry: LexiconEntry | None = None
    feature_score: float = 0

    @property
    def key(self) -> str:
        return f"{self.start}:{self.end}:{self.entity_type}"


@cache
def rules() -> dict:
    return json.loads(files("jev_chinesener.data").joinpath("rules.json").read_text())


def build_graph(text: str, lexicon: Lexicon, max_length: int = 16) -> list[Edge]:
    """All edges copy a contiguous source span; singletons guarantee reachability."""
    edges: dict[tuple, Edge] = {}

    def add(start, end, source, kind="unknown", score=0, entry=None):
        key = (start, end, kind, entry.entity_id if entry else None)
        if key in edges:
            edges[key].sources.add(source)
            edges[key].feature_score = max(edges[key].feature_score, score)
        else:
            edges[key] = Edge(start, end, text[start:end], kind, {source}, entry, score)

    for start, char in enumerate(text):
        separator = char.isspace() or (not char.isalnum() and not "\u3400" <= char <= "\u9fff")
        add(start, start + 1, "character_fallback", "separator" if separator else "unknown", -1)
        if not separator:
            for end in range(start + 2, min(len(text), start + max_length) + 1):
                word = text[start:end]
                if not all(c.isalnum() for c in word):
                    break
                add(start, end, "unknown_substring", score=-0.6 * len(word) - 1)

    for start, end, entry in lexicon.matches(text):
        canonical = text[start:end] == entry.canonical_name
        add(
            start,
            end,
            "lexicon" if canonical else "alias",
            entry.entity_type,
            len(text[start:end]) * (1.7 if canonical else 1.2) + 0.5,
            entry,
        )

    for word, start, end in _TOKENIZER.tokenize(text, HMM=False):
        if any(c.isalnum() for c in word):
            add(start, end, "jieba", score=0.2 * len(word) - 0.6)

    spec = rules()
    for start in range(len(text)):
        for end in range(start + 2, min(len(text), start + max_length) + 1):
            word = text[start:end]
            if not re.fullmatch(r"[\u3400-\u9fff]+", word) or word in spec["negative_surfaces"]:
                continue
            for suffix, kind in spec["suffixes"].items():
                if len(word) > len(suffix) and word.endswith(suffix):
                    add(start, end, "morphology", kind, 0.55 * len(word) - 0.8)
                    break
    for match in re.finditer(r"[0-9０-９一二三四五六七八九十百]+(?:号楼|号|栋|幢|单元|室)", text):
        add(match.start(), match.end(), "house_number", "house_number", len(match[0]) * 0.8)
    return sorted(
        edges.values(), key=lambda e: (e.start, e.end, e.key, e.entry.entity_id if e.entry else "")
    )
