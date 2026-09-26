from fastapi import FastAPI, HTTPException

from .cache import LocalLimitError
from .models import SegmentRequest, SegmentResponse
from .service import Segmenter, UnsupportedScope


def create_app(segmenter: Segmenter | None = None) -> FastAPI:
    app = FastAPI(
        title="Jev-ChineseNER",
        version="0.1.0",
        description="阶段一：中文单地名与短地址的双粒度分词",
    )
    engine = segmenter or Segmenter()

    @app.post("/v1/toponyms/segment", response_model=SegmentResponse)
    async def segment(request: SegmentRequest):
        try:
            return await engine.segment(request)
        except LocalLimitError as exc:
            raise HTTPException(status_code=429, detail={"code": exc.code}) from None
        except UnsupportedScope as exc:
            raise HTTPException(
                status_code=422, detail={"code": "unsupported_scope", "message": str(exc)}
            ) from None

    @app.get("/health")
    async def health():
        return {
            "status": "ok",
            "backend": engine.settings.backend,
            "model": engine.settings.model,
            "chinese_validation": "not_run",
        }

    return app


app = create_app()
