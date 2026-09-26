"""Run: uv run python scripts/demo.py. Never requires or uses an API key."""

import asyncio

from jev_chinesener.config import Settings
from jev_chinesener.models import SegmentRequest
from jev_chinesener.service import Segmenter


async def main():
    engine = Segmenter(Settings(backend="mock"))
    for text in [
        "江苏省南京市栖霞区仙林大道",
        "南京市长江大桥",
        "上海市南京东路",
        "东莞市",
        "内蒙古自治区",
        "广西壮族自治区",
        "南京大学",
        "星海路１３８号",
    ]:
        result = await engine.segment(SegmentRequest(text=text))
        print(f"{text} [{result.status}]")
        print("  地理单元：", "/".join(u.text for u in result.units))
        for unit in result.units:
            print(
                f"  {unit.text} ({unit.entity_type}): "
                + " / ".join(f"{c.text}<{c.role}>" for c in unit.components)
            )
        print(
            f"  fast_path={result.diagnostics['fast_path']}; "
            f"model_used={result.versions['model_used']}"
        )


if __name__ == "__main__":
    asyncio.run(main())
