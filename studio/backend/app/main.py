"""Anthotype Studio API.

Upload a design PNG, watch the pipeline run, download the code-native site.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from . import config
from .imageutil import MAX_UPLOAD_BYTES, UploadError
from .jobs import STAGES, JobStore
from .runner import PipelineRunner

app = FastAPI(title="Anthotype Studio", version="0.1.0")

# The Vite dev server proxies /api, but allow direct access too.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"], allow_headers=["*"],
)

runner = PipelineRunner(None)      # store injected on the next line
store = JobStore(runner)
runner.store = store

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "stages": [{"name": n, "message": m} for n, _, m in STAGES],
        "vision": config.vision.describe(),
    }


@app.get("/api/jobs")
def list_jobs() -> dict:
    return {"jobs": [j.to_dict() for j in store.list()]}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    return job.to_dict()


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...)) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix and suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"unsupported file type {suffix!r}")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty upload")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"file too large (max {MAX_UPLOAD_BYTES // (1024*1024)} MB)")

    # Validate decodability up front so a bad upload fails immediately, not
    # three stages into a build.
    try:
        from PIL import Image
        import io
        Image.open(io.BytesIO(raw)).verify()
    except UploadError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"not a readable image: {exc}") from exc

    job = store.create(raw, filename=file.filename)
    return {"id": job.id}


def _job_file(job_id: str, name: str) -> Path:
    job = store.get(job_id)
    if not job:
        raise HTTPException(404, "no such job")
    p = job.dir / name
    if not p.is_file():
        raise HTTPException(404, f"{name} is not ready")
    return p


@app.get("/api/jobs/{job_id}/preview")
def preview(job_id: str) -> FileResponse:
    """The built, self-contained page (served into the UI's iframe)."""
    return FileResponse(_job_file(job_id, "index.html"), media_type="text/html")


@app.get("/api/jobs/{job_id}/ref")
def reference(job_id: str) -> FileResponse:
    return FileResponse(_job_file(job_id, "ref.png"), media_type="image/png")


@app.get("/api/jobs/{job_id}/download")
def download(job_id: str) -> FileResponse:
    p = _job_file(job_id, "dist.zip")
    job = store.get(job_id)
    name = Path((job.src or {}).get("filename") or job_id).stem
    return FileResponse(p, media_type="application/zip",
                        filename=f"{name}-site.zip")


@app.exception_handler(UploadError)
def _upload_error(_req, exc: UploadError) -> JSONResponse:  # pragma: no cover
    return JSONResponse({"detail": str(exc)}, status_code=400)
