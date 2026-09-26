import argparse
import asyncio
import json
from dataclasses import asdict

from .config import Settings
from .models import SegmentRequest
from .service import Segmenter


def main():
    parser = argparse.ArgumentParser(description="Jev 驱动的中文地名多粒度分词器")
    parser.add_argument("text")
    parser.add_argument("--backend", choices=["mock", "local", "jev"])
    parser.add_argument(
        "--input-kind", choices=["place_name", "address", "text"], default="address"
    )
    parser.add_argument(
        "--granularity", choices=["geographic_unit", "name_component", "both"], default="both"
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--region-context")
    parser.add_argument("--no-components", action="store_true")
    parser.add_argument("--no-fast-path", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="输出候选与第一轮问题，不调用模型")
    args = parser.parse_args()
    try:
        settings = Settings.from_env()
        if args.backend:
            settings.backend = args.backend
        settings.fast_path = not args.no_fast_path
        engine = Segmenter(settings)
        request = SegmentRequest(
            text=args.text,
            input_kind=args.input_kind,
            granularity=args.granularity,
            top_k=args.top_k,
            return_components=not args.no_components,
            region_context=args.region_context,
        )
        if args.dry_run:
            edges, state, questions = engine.prepare(request)
            output = {
                "model": settings.model,
                "state": state,
                "candidate_count": len(edges),
                "candidates": [
                    {
                        "text": e.text,
                        "span": [e.start, e.end],
                        "type": e.entity_type,
                        "sources": sorted(e.sources),
                        "feature_score": e.feature_score,
                    }
                    for e in edges
                ],
                "questions": [asdict(q) for q in questions],
                "note": "dry-run 无网络；第二轮问题依赖第一轮解码，仅运行时构造",
            }
        else:
            output = asyncio.run(engine.segment(request)).model_dump(mode="json")
        print(json.dumps(output, ensure_ascii=False, indent=2))
    except ValueError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
