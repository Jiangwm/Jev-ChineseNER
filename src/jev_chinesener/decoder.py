import math
from dataclasses import dataclass

from .candidates import Edge
from .models import Judgment


@dataclass
class Path:
    score: float
    edges: list[Edge]


def decode(
    length: int,
    edges: list[Edge],
    cuts: dict[int, float],
    types: dict[str, Judgment] | None = None,
    top_k: int = 3,
) -> list[Path]:
    """Exact k-best DAG paths with additive scores; no province/city ordering grammar.

    Every internal character gap contributes once: log(1-p) inside an edge,
    log(p) at an edge end. Scores are ranking energies, not calibrated probabilities.
    """
    types = types or {}

    def path_key(path):
        return tuple(
            (
                edge.start,
                edge.end,
                types[edge.key].choice if edge.key in types else edge.entity_type,
            )
            for edge in path.edges
        )

    outgoing: dict[int, list[Edge]] = {}
    for edge in edges:
        if not 0 <= edge.start < edge.end <= length:
            raise ValueError("candidate outside source")
        outgoing.setdefault(edge.start, []).append(edge)
    best: list[list[Path]] = [[] for _ in range(length + 1)]
    best[0] = [Path(0, [])]
    for pos in range(length):
        for edge in outgoing.get(pos, []):
            score = edge.feature_score
            for gap in range(edge.start + 1, edge.end):
                p = min(1 - 1e-6, max(1e-6, cuts.get(gap, 0.5)))
                score += math.log1p(-p)
            if edge.end < length:
                p = min(1 - 1e-6, max(1e-6, cuts.get(edge.end, 0.5)))
                score += math.log(p)
            judgment = types.get(edge.key)
            if judgment and judgment.probabilities:
                kind = judgment.choice
                score += 0.7 * math.log(max(1e-6, judgment.probabilities.get(kind, 0)))
            best[edge.end].extend(
                Path(path.score + score, [*path.edges, edge]) for path in best[pos]
            )
            best[edge.end].sort(key=lambda path: (-path.score, path_key(path)))
            # Different evidence for an identical span/type is not a segmentation alternative.
            unique, seen = [], set()
            for path in best[edge.end]:
                key = path_key(path)
                if key not in seen:
                    unique.append(path)
                    seen.add(key)
            best[edge.end] = unique[:top_k]
    if not best[length]:
        raise ValueError("candidate graph does not cover source")
    return best[length]
