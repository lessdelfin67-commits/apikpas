from __future__ import annotations

import asyncio
import contextlib
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import settings
from .media import build_ffmpeg_command, extension_for

_TIME_RE = re.compile(r"out_time_ms=(\d+)")
_SPEED_RE = re.compile(r"speed=([^\r\n]+)")


@dataclass
class Job:
    job_id: str
    source: Path
    request: Any
    output: Path
    duration: float | None = None
    status: str = "queued"
    progress: float = 0.0
    speed: str | None = None
    eta_seconds: float | None = None
    error: str | None = None
    task: asyncio.Task | None = field(default=None, repr=False)


class JobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    def create(self, job_id: str, source: Path, request: Any, duration: float | None) -> Job:
        output = settings.output_dir / f"{job_id}.{extension_for(request)}"
        job = Job(job_id, source, request, output, duration)
        self.jobs[job_id] = job
        job.task = asyncio.create_task(self._run(job))
        return job

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    async def _run(self, job: Job) -> None:
        async with self.semaphore:
            job.status = "processing"
            command = build_ffmpeg_command(job.source, job.output, job.request)
            started = time.monotonic()
            try:
                process = await asyncio.create_subprocess_exec(*command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                stderr_task = asyncio.create_task(process.stderr.read())
                assert process.stdout is not None
                buffer = ""
                async for chunk in process.stdout:
                    buffer += chunk.decode(errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        match = _TIME_RE.search(line)
                        if match and job.duration and job.duration > 0:
                            elapsed = int(match.group(1)) / 1_000_000
                            job.progress = min(99.9, round(elapsed / job.duration * 100, 2))
                            if job.progress > 0:
                                job.eta_seconds = max(0, round((time.monotonic() - started) * (100 / job.progress - 1), 2))
                        speed = _SPEED_RE.search(line)
                        if speed:
                            job.speed = speed.group(1).strip()
                returncode = await process.wait()
                error_text = (await stderr_task).decode(errors="replace")
                if returncode != 0:
                    raise RuntimeError(error_text[-2000:] or f"ffmpeg terminou com código {returncode}")
                job.status = "completed"
                job.progress = 100.0
                job.eta_seconds = 0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                job.output.unlink(missing_ok=True)
            finally:
                job.source.unlink(missing_ok=True)

    async def cleanup(self) -> None:
        while True:
            cutoff = time.time() - settings.cleanup_hours * 3600
            for directory in (settings.upload_dir, settings.output_dir, settings.temp_dir):
                for path in directory.iterdir():
                    if path.name == ".gitkeep":
                        continue
                    with contextlib.suppress(OSError):
                        if path.stat().st_mtime < cutoff:
                            path.unlink()
            await asyncio.sleep(3600)


manager = JobManager()
