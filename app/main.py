from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import secrets
import uuid
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Security, UploadFile
from fastapi.responses import FileResponse
from fastapi.security import APIKeyHeader

from .config import settings
from .jobs import manager
from .media import materialize_source, run_probe, summarize_probe, validate_conversion
from .schemas import AnalyzeResponse, ConvertRequest, JobResponse

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="API para análise e conversão de mídia autorizada pelo usuário usando FFmpeg.",
    docs_url="/docs",
    redoc_url="/redoc",
)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
_cleanup_task: asyncio.Task | None = None


async def require_api_key(api_key: str | None = Security(api_key_header)) -> None:
    if not api_key or not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API key inválida ou ausente", headers={"WWW-Authenticate": "ApiKey"})


@app.on_event("startup")
async def startup() -> None:
    global _cleanup_task
    _cleanup_task = asyncio.create_task(manager.cleanup())


@app.on_event("shutdown")
async def shutdown() -> None:
    if _cleanup_task:
        _cleanup_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await _cleanup_task


async def _prepare(upload: UploadFile | None, source: str | None) -> tuple[Path, dict]:
    token = uuid.uuid4().hex
    path = await materialize_source(upload, source, token)
    try:
        probe = await run_probe(path)
        return path, summarize_probe(probe, path.stat().st_size)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _job_response(job) -> JobResponse:
    return JobResponse(job_id=job.job_id, status=job.status, progress=job.progress, speed=job.speed, eta_seconds=job.eta_seconds, error=job.error, filename=job.output.name if job.status == "completed" else None)


@app.post("/analyze", response_model=AnalyzeResponse, summary="Analisa uma mídia e retorna somente opções detectadas")
async def analyze(_: None = Depends(require_api_key), file: UploadFile | None = File(None), source: str | None = Form(None)) -> AnalyzeResponse:
    path, summary = await _prepare(file, source)
    try:
        return AnalyzeResponse(**summary)
    finally:
        path.unlink(missing_ok=True)


@app.post("/convert", response_model=JobResponse, status_code=202, summary="Cria um job de conversão com FFmpeg")
async def convert(
    _: None = Depends(require_api_key),
    tipo: str = Form(..., description="video ou audio"),
    formato: str = Form(..., description="formato de saída compatível"),
    qualidade: str | None = Form(None),
    resolucao: str | None = Form(None),
    fps: float | None = Form(None),
    codec: str | None = Form(None),
    bitrate: int | None = Form(None, description="kbps"),
    file: UploadFile | None = File(None),
    source: str | None = Form(None),
) -> JobResponse:
    try:
        request = ConvertRequest(type=tipo, format=formato, quality=qualidade, resolution=resolucao, fps=fps, codec=codec, bitrate=bitrate)
    except Exception as exc:
        raise HTTPException(422, f"parâmetros de conversão inválidos: {exc}") from exc
    path, summary = await _prepare(file, source)
    try:
        validate_conversion(request, summary)
        job_id = str(uuid.uuid4())
        job = manager.create(job_id, path, request, summary.get("duration_seconds"))
        return _job_response(job)
    except Exception:
        path.unlink(missing_ok=True)
        raise


@app.get("/jobs/{job_id}", response_model=JobResponse, summary="Consulta status e progresso do job")
async def get_job(job_id: str, _: None = Depends(require_api_key)) -> JobResponse:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job não encontrado")
    return _job_response(job)


@app.get("/download/{job_id}", summary="Baixa o arquivo de um job concluído")
async def download(job_id: str, _: None = Depends(require_api_key)) -> FileResponse:
    job = manager.get(job_id)
    if not job:
        raise HTTPException(404, "job não encontrado")
    if job.status != "completed" or not job.output.is_file():
        raise HTTPException(409, "o job ainda não foi concluído")
    return FileResponse(job.output, filename=job.output.name, media_type=mimetypes.guess_type(job.output.name)[0] or "application/octet-stream")


@app.get("/health", include_in_schema=False)
async def health() -> dict[str, str]:
    return {"status": "ok"}
