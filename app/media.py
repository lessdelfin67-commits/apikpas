from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, UploadFile

from .config import settings

SUPPORTED_VIDEO_FORMATS = {"mp4", "webm", "mkv", "mov", "avi", "flv", "mpeg", "ts"}
SUPPORTED_AUDIO_FORMATS = {"mp3", "m4a", "wav", "flac", "ogg", "opus"}
COMMON_AUDIO_BITRATES = [64, 96, 128, 160, 192, 256, 320]
AUDIO_OUTPUT_CODECS = {
    "mp3": {"mp3", "libmp3lame"},
    "m4a": {"aac", "alac"},
    "wav": {"pcm_s16le", "pcm_s24le", "pcm_s32le"},
    "flac": {"flac"},
    "ogg": {"vorbis", "libvorbis", "opus", "libopus"},
    "opus": {"opus", "libopus"},
}
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str | None, fallback: str = "media") -> str:
    stem = Path(name or fallback).name
    stem = SAFE_NAME.sub("_", stem).strip("._") or fallback
    return stem[:180]


def validate_source_url(source: str) -> str:
    parsed = urlparse(source)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(422, "source deve ser uma URL HTTP/HTTPS válida")
    if parsed.username or parsed.password:
        raise HTTPException(422, "URLs com credenciais embutidas não são aceitas")
    return source


async def save_upload(upload: UploadFile, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with destination.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(413, "arquivo excede o limite máximo configurado")
                output.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "arquivo vazio")
    return destination


async def download_url(source: str, destination: Path) -> Path:
    validate_source_url(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        timeout = httpx.Timeout(settings.request_timeout_seconds, read=settings.max_url_seconds)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            async with client.stream("GET", source, headers={"User-Agent": "authorized-media-api/1.0"}) as response:
                response.raise_for_status()
                content_length = int(response.headers.get("content-length", "0") or 0)
                if content_length > settings.max_url_bytes:
                    raise HTTPException(413, "recurso remoto excede o limite máximo configurado")
                with destination.open("wb") as output:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > settings.max_url_bytes:
                            raise HTTPException(413, "recurso remoto excede o limite máximo configurado")
                        output.write(chunk)
    except httpx.HTTPError as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, f"não foi possível obter a URL: {exc}") from exc
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if total == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(422, "recurso remoto vazio")
    return destination


async def materialize_source(upload: UploadFile | None, source: str | None, token: str) -> Path:
    if bool(upload) == bool(source):
        raise HTTPException(422, "envie exatamente um arquivo ou uma URL em source")
    if upload:
        return await save_upload(upload, settings.upload_dir / f"{token}_{safe_filename(upload.filename)}")
    return await download_url(source or "", settings.upload_dir / f"{token}_remote_media")


async def run_probe(path: Path) -> dict[str, Any]:
    command = [settings.ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]
    process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise HTTPException(422, f"mídia inválida ou não suportada: {stderr.decode(errors='replace')[-500:]}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "ffprobe retornou dados inválidos") from exc


def _float(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _fps(stream: dict[str, Any]) -> float | None:
    value = stream.get("avg_frame_rate") or stream.get("r_frame_rate")
    if not value or value in {"0/0", "N/A"}:
        return None
    if "/" in str(value):
        numerator, denominator = str(value).split("/", 1)
        try:
            return round(float(numerator) / float(denominator), 3)
        except (ValueError, ZeroDivisionError):
            return None
    return _float(value)


def _format_aliases(format_name: str) -> set[str]:
    aliases = set()
    for item in format_name.split(","):
        item = item.lower().strip()
        aliases.add({"matroska": "mkv", "mov,mp4,m4a,3gp,3g2,mj2": "mp4", "mpegts": "ts", "mpeg": "mpeg", "ogg": "ogg", "webm": "webm"}.get(item, item))
    return aliases


def summarize_probe(probe: dict[str, Any], size_bytes: int | None = None) -> dict[str, Any]:
    streams = probe.get("streams", [])
    fmt = probe.get("format", {})
    video = [s for s in streams if s.get("codec_type") == "video"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    resolutions = sorted({f"{s.get('width')}x{s.get('height')}" for s in video if s.get("width") and s.get("height")}, key=lambda x: (int(x.split("x")[1]), int(x.split("x")[0])), reverse=True)
    qualities = sorted({f"{s.get('height')}p" for s in video if s.get("height")}, key=lambda x: int(x[:-1]), reverse=True)
    fps = sorted({value for s in video if (value := _fps(s)) is not None})
    video_codecs = sorted({str(s.get("codec_name")) for s in video if s.get("codec_name")})
    audio_codecs = sorted({str(s.get("codec_name")) for s in audio if s.get("codec_name")})
    formats = _format_aliases(str(fmt.get("format_name", "")))
    video_formats = sorted(formats & SUPPORTED_VIDEO_FORMATS) if video else []
    audio_formats = sorted(formats & SUPPORTED_AUDIO_FORMATS) if audio else []
    bitrates = sorted({round(int(s["bit_rate"]) / 1000) for s in audio if str(s.get("bit_rate", "")).isdigit() and int(s["bit_rate"]) > 0})
    if audio and not bitrates:
        bitrates = COMMON_AUDIO_BITRATES.copy()
    media_type = "video" if video else "audio"
    return {
        "title": fmt.get("tags", {}).get("title") or Path(str(fmt.get("filename", "media"))).stem,
        "duration_seconds": _float(fmt.get("duration")),
        "size_bytes": size_bytes or (int(fmt["size"]) if str(fmt.get("size", "")).isdigit() else None),
        "media_type": media_type,
        "resolutions": resolutions,
        "qualities": qualities,
        "fps": fps,
        "video_codecs": video_codecs,
        "audio_codecs": audio_codecs,
        "video_formats": video_formats,
        "audio_formats": audio_formats,
        "audio_bitrates_kbps": bitrates,
        "streams": streams,
    }


def validate_conversion(request: Any, summary: dict[str, Any]) -> None:
    allowed_formats = (SUPPORTED_VIDEO_FORMATS if request.type.value == "video" else SUPPORTED_AUDIO_FORMATS)
    if request.format not in allowed_formats:
        raise HTTPException(422, f"formato de saída não suportado: {request.format}")
    if request.type.value == "video":
        if not summary["resolutions"]:
            raise HTTPException(422, "a origem não contém vídeo")
        if request.quality and request.quality not in summary["qualities"]:
            raise HTTPException(422, "qualidade não disponível na origem; use uma opção retornada por /analyze")
        if request.resolution and request.resolution not in summary["resolutions"]:
            raise HTTPException(422, "resolução não disponível na origem; use uma opção retornada por /analyze")
        if request.fps and not any(abs(request.fps - value) < 0.01 for value in summary["fps"]):
            raise HTTPException(422, "FPS não disponível na origem; use uma opção retornada por /analyze")
        if request.codec and request.codec not in summary["video_codecs"]:
            raise HTTPException(422, "codec de vídeo não disponível na origem; use uma opção retornada por /analyze")
    else:
        if not summary["audio_codecs"]:
            raise HTTPException(422, "a origem não contém áudio")
        if request.bitrate and request.bitrate not in summary["audio_bitrates_kbps"]:
            raise HTTPException(422, "bitrate não disponível; use uma opção retornada por /analyze")
        if request.codec and request.codec not in summary["audio_codecs"]:
            raise HTTPException(422, "codec de áudio não disponível na origem; use uma opção retornada por /analyze")
        if request.codec and request.codec not in AUDIO_OUTPUT_CODECS[request.format]:
            raise HTTPException(422, "codec de áudio incompatível com o formato de saída")


def extension_for(request: Any) -> str:
    return request.format.lower().lstrip(".")


def build_ffmpeg_command(source: Path, output: Path, request: Any) -> list[str]:
    args = [settings.ffmpeg_bin, "-hide_banner", "-y", "-i", str(source)]
    if request.type.value == "video":
        args += ["-map", "0:v:0", "-map", "0:a?", "-c:v", request.codec or "libx264"]
        if request.quality:
            height = int(request.quality[:-1])
            args += ["-vf", f"scale=-2:{height}"]
        elif request.resolution:
            args += ["-vf", f"scale={request.resolution.replace('x', ':')}"]
        if request.fps:
            args += ["-r", str(request.fps)]
        args += ["-c:a", "aac", "-movflags", "+faststart"]
    else:
        codec = request.codec or ({"mp3": "libmp3lame", "m4a": "aac", "wav": "pcm_s16le", "flac": "flac", "ogg": "libvorbis", "opus": "libopus"}[request.format])
        args += ["-map", "0:a:0", "-vn", "-c:a", codec]
        if request.bitrate and request.format not in {"wav", "flac"}:
            args += ["-b:a", f"{request.bitrate}k"]
    args += ["-progress", "pipe:1", "-nostats", str(output)]
    return args
