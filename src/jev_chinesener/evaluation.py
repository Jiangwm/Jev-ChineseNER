"""Small reproducible evaluation harness. No fixture score is a production claim."""

import argparse
import asyncio
import json
import math
import time
from collections import defaultdict
from itertools import pairwise
from pathlib import Path

import jieba

from .candidates import build_graph
from .config import Settings
from .gold import GoldDocument, validate_dataset
from .models import SegmentRequest
from .service import Segmenter

ROUTES = [
    "jieba",
    "jieba_lexicon",
    "local_graph",
    "boundary_jev",
    "hybrid_jev",
    "selective_jev",
    "mock",
]


def boundaries(spans):
    return {span[1] for span in spans[:-1]}


def prf(tp, predicted, expected):
    precision = tp / predicted if predicted else float(expected == 0)
    recall = tp / expected if expected else float(predicted == 0)
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0,
    }


def probability_metrics(observations):
    """Boundary Brier / equal-width ECE; no fitting on evaluation labels."""
    if not observations:
        return {"brier": None, "ece_10_bins": None, "reliability_curve": []}
    brier = sum((p - y) ** 2 for p, y in observations) / len(observations)
    ece, curve = 0, []
    for i in range(10):
        values = [(p, y) for p, y in observations if min(9, int(p * 10)) == i]
        if values:
            ece += abs(sum(p - y for p, y in values)) / len(observations)
            curve.append(
                {
                    "bin": [i / 10, (i + 1) / 10],
                    "count": len(values),
                    "mean_probability": sum(p for p, _ in values) / len(values),
                    "observed_frequency": sum(y for _, y in values) / len(values),
                }
            )
    return {"brier": brier, "ece_10_bins": ece, "reliability_curve": curve}


def component_metrics(cases):
    """Match components within their parent; macro-average roles present on either side."""
    span_tp = predicted_count = gold_count = 0
    counts = defaultdict(lambda: [0, 0, 0])
    for predicted, gold in cases:
        pred_spans = {part[:-1] for part in predicted}
        gold_spans = {part[:-1] for part in gold}
        span_tp += len(pred_spans & gold_spans)
        predicted_count += len(pred_spans)
        gold_count += len(gold_spans)
        for role in {part[-1] for part in predicted | gold}:
            p = {part for part in predicted if part[-1] == role}
            g = {part for part in gold if part[-1] == role}
            for i, value in enumerate((len(p & g), len(p), len(g))):
                counts[role][i] += value
    per_role = {role: prf(*values) for role, values in sorted(counts.items())}
    return {
        "span_parent": prf(span_tp, predicted_count, gold_count),
        "role_macro_f1": sum(v["f1"] for v in per_role.values()) / len(per_role)
        if per_role
        else None,
        "per_role": per_role,
        "role_matching": "exact_parent_and_component_span",
    }


async def evaluate(rows: list[dict], route: str) -> dict:
    from .providers import JevJudge
    from .questions import boundary_questions

    if route not in ROUTES:
        raise ValueError("unknown evaluation route")
    backend = (
        "jev"
        if route in {"hybrid_jev", "boundary_jev", "selective_jev"}
        else ("mock" if route == "mock" else "local")
    )
    # Only the explicit selective route measures the verified-input fast channel.
    engine = Segmenter(Settings(backend=backend, fast_path=route == "selective_jev"))
    tokenizer = jieba.Tokenizer() if route == "jieba_lexicon" else None
    if tokenizer:
        for entry in engine.lexicon.entries:
            for surface in [entry.canonical_name, *entry.aliases]:
                tokenizer.add_word(surface, freq=1_000_000)
    exact = btp = bp = bg = stp = sp = sg = ctp = cp = cg = 0
    oov_hit = oov_total = requests = tokens = degraded = 0
    candidate_hits = typed_candidate_hits = candidate_total = fast_hits = reachable = 0
    component_cases = []
    latencies, observations, per_case = [], [], []
    for row in rows:
        start = time.perf_counter()
        text = row["text"]
        gold = [tuple(unit["span"]) for unit in row["units"]]
        predicted_components = set()
        predicted_types = set()
        if route in {"jieba", "jieba_lexicon"}:
            spans = [(s, e) for _, s, e in (tokenizer or jieba).tokenize(text, HMM=False)]
            if tokenizer:
                for a, b, entry in engine.lexicon.matches(text):
                    if (a, b) not in spans:
                        continue
                    predicted_types.add((a, b, entry.entity_type))
                    if text[a:b] == entry.canonical_name:
                        predicted_components.update(
                            (a, b, a + c.span.start, a + c.span.end, c.role)
                            for c in entry.verified_components
                        )
        elif route == "boundary_jev":
            # Minimal prototype: exactly one Noul per original gap; no graph features.
            from .providers import ProviderError

            try:
                result = await JevJudge(engine.settings).evaluate(
                    {
                        "source_text": text,
                        "input_kind": row["input_kind"],
                        "region_context": row.get("region_context"),
                    },
                    boundary_questions(text),
                )
                cuts = [
                    int(q.rsplit(":", 1)[1]) for q, a in result.answers.items() if a.noul >= 0.5
                ]
                points = [0, *sorted(cuts), len(text)]
                spans = list(pairwise(points))
                requests += result.requests
                tokens += result.usage.get("input_tokens", 0)
                observations.extend(
                    (a.noul, int(int(q.rsplit(":", 1)[1]) in boundaries(gold)))
                    for q, a in result.answers.items()
                )
            except ProviderError as exc:
                raise RuntimeError(f"真实 Jev 评测失败，不以 mock 代替：{exc}") from None
        else:
            result = await engine.segment(
                SegmentRequest(
                    text=text,
                    input_kind=row["input_kind"],
                    top_k=1,
                    region_context=row.get("region_context"),
                )
            )
            if route in {"hybrid_jev", "selective_jev"} and result.status == "degraded":
                raise RuntimeError("真实 Jev 评测发生回退；本次不可报告为 Jev 准确率")
            spans = [(u.span.start, u.span.end) for u in result.units]
            predicted_types = {(u.span.start, u.span.end, u.entity_type) for u in result.units}
            predicted_components = {
                (u.span.start, u.span.end, c.span.start, c.span.end, c.role)
                for u in result.units
                for c in u.components
            }
            requests += result.diagnostics["api_requests"]
            tokens += result.diagnostics["usage"].get("input_tokens", 0)
            degraded += result.status == "degraded"
            fast_hits += result.diagnostics["fast_path"]
            observations.extend(
                (a.noul, int(int(a.question_id.rsplit(":", 1)[1]) in boundaries(gold)))
                for a in result.raw_model_probabilities
                if a.question_id.startswith("unit:cut:")
            )
        latencies.append((time.perf_counter() - start) * 1000)
        if route in {"local_graph", "hybrid_jev", "selective_jev", "mock"}:
            # Diagnostic pass is outside timing so recall measurement does not inflate latency.
            graph = build_graph(text, engine.lexicon, engine.settings.max_candidate_length)
            candidate_spans = {(e.start, e.end) for e in graph}
            typed_candidates = {(e.start, e.end, e.entity_type) for e in graph}
            candidate_hits += len(set(gold) & candidate_spans)
            candidate_total += len(gold)
            typed_candidate_hits += sum(
                (u["span"][0], u["span"][1], u["entity_type"]) in typed_candidates
                for u in row["units"]
            )
            reachable += all(span in candidate_spans for span in gold)
        gb, pb = boundaries(gold), boundaries(spans)
        btp += len(gb & pb)
        bp += len(pb)
        bg += len(gb)
        stp += len(set(gold) & set(spans))
        sp += len(spans)
        sg += len(gold)
        exact += spans == gold
        gold_components = {
            (u["span"][0], u["span"][1], c["span"][0], c["span"][1], c["role"])
            for u in row["units"]
            for c in u.get("components", [])
        }
        ctp += len(gold_components & predicted_components)
        cp += len(predicted_components)
        cg += len(gold_components)
        component_cases.append((predicted_components, gold_components))
        for unit in row["units"]:
            if unit.get("oov", False):
                oov_total += 1
                oov_hit += tuple(unit["span"]) in spans
        gold_types = {(u["span"][0], u["span"][1], u["entity_type"]) for u in row["units"]}
        per_case.append(
            {
                "id": row["id"],
                "predicted_spans": spans,
                "exact_match": spans == gold,
                "typed_tp": len(gold_types & predicted_types),
                "typed_predicted": len(predicted_types),
                "typed_gold": len(gold_types),
            }
        )
    count = len(rows)
    ordered = sorted(latencies)
    has_structure = route not in {"jieba", "boundary_jev"}
    return {
        "route": route,
        "samples": count,
        "fast_path_disabled": route != "selective_jev",
        "fast_path_rate": fast_hits / count if count else None,
        "candidate_recall": {
            "span": candidate_hits / candidate_total,
            "span_and_local_type": typed_candidate_hits / candidate_total,
            "stage": "before_Jev",
            "gold_path_reachable_rate": reachable / count if count else None,
        }
        if candidate_total
        else None,
        "interpretation": "演示集冒烟评测；非独立测试集，不证明 Jev 中文优于本地方案",
        "exact_match": exact / count if count else None,
        "boundary": prf(btp, bp, bg),
        "unit_span": prf(stp, sp, sg),
        "typed_unit": prf(
            sum(x["typed_tp"] for x in per_case),
            sum(x["typed_predicted"] for x in per_case),
            sum(x["typed_gold"] for x in per_case),
        )
        if has_structure
        else None,
        "component_span_role_parent": prf(ctp, cp, cg) if has_structure else None,
        "components": component_metrics(component_cases) if has_structure else None,
        "oov_recall": oov_hit / oov_total if oov_total else None,
        "boundary_calibration": probability_metrics(observations),
        "latency_ms": {
            "p50": ordered[math.ceil(count * 0.5) - 1] if count else None,
            "p95": ordered[math.ceil(count * 0.95) - 1] if count else None,
        },
        "api_requests": requests,
        "input_tokens": tokens,
        "cost_usd": None,
        "degraded_rate": degraded / count if count else None,
        "pending_metrics": [
            "held_out_stratification",
            "human_ambiguity_review",
            "cost_from_billing",
        ],
        "cases": per_case,
    }


def main():
    parser = argparse.ArgumentParser(description="小金标准评测；真实 Jev 失败时中止，禁止冒充结果")
    parser.add_argument("--gold", type=Path, default=Path("fixtures/gold.jsonl"))
    parser.add_argument("--route", choices=ROUTES, default="local_graph")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", choices=["demo", "train", "dev", "test"])
    args = parser.parse_args()
    try:
        rows = [
            GoldDocument.model_validate_json(line)
            for line in args.gold.read_text().splitlines()
            if line.strip()
        ]
        validate_dataset(rows)
        selected = [row for row in rows if not args.split or row.split == args.split]
        if not selected:
            raise ValueError("所选 split 不能为空")
        report = asyncio.run(
            evaluate([row.model_dump(mode="json") for row in selected], args.route)
        )
        report["split"] = args.split or "all"
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n")
    print(payload)


if __name__ == "__main__":
    main()
