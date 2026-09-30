"""Job store and the serialized worker that runs builds one at a time.

State lives on disk (`data/jobs/<id>/status.json`) so a job survives a backend
restart as a record, and in memory for fast polling.  Builds are heavy
(potrace + a full Astro build), so a single worker serializes them; extra jobs
queue.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from .config import JOBS_DIR

# The stage machine, shared with the frontend so both agree on the stepper.
STAGES: list[tuple[str, float, str]] = [
    ("received", 0.02, "Upload received"),
    ("extracting", 0.10, "Reading the page's structure and copy"),
    ("generating", 0.22, "Building the page structure and stylesheet"),
    ("tracing", 0.32, "Tracing the artwork with potrace"),
    ("composing", 0.68, "Composing the self-contained page"),
    ("building", 0.78, "Building the Astro site"),
    ("verifying", 0.92, "Checking the artwork and the page structure"),
    ("packaging", 0.97, "Packaging the download"),
    ("done", 1.00, "Done"),
]
STAGE_INDEX = {name: i for i, (name, _, _) in enumerate(STAGES)}
TERMINAL = {"done", "failed"}


@dataclass
class Job:
    id: str
    created: float
    updated: float
    status: str = "queued"          # queued | running | done | failed
    stage: str = "received"
    progress: float = 0.0
    message: str = ""
    logs: list[str] = field(default_factory=list)
    error: str | None = None
    warnings: list[str] = field(default_factory=list)
    score: float | None = None      # fidelity of the ARTWORK region (lower better)
    pct_over_30: float | None = None
    whole_score: float | None = None  # whole-stage mean, informational only
    whole_pct: float | None = None
    src: dict | None = None         # source image info
    blocks: list[dict] = field(default_factory=list)
    structure: list[dict] | dict | None = None   # page structure summary
    structure_issues: list[str] = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)   # {zip, preview, ...} relative paths

    @property
    def dir(self) -> Path:
        return JOBS_DIR / self.id

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    def __init__(self, runner: Callable[[Job], None]) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="anthotype-job")
        self._runner = runner
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    # -- persistence --------------------------------------------------------
    def _load_existing(self) -> None:
        for d in sorted(JOBS_DIR.glob("*")):
            f = d / "status.json"
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text())
                # A job that was mid-flight when the process died is not running.
                if data.get("status") == "running":
                    data["status"] = "failed"
                    data["error"] = "interrupted by a backend restart"
                self._jobs[data["id"]] = Job(**data)
            except Exception:  # noqa: BLE001 - a corrupt record must not block startup
                continue

    def _persist(self, job: Job) -> None:
        job.dir.mkdir(parents=True, exist_ok=True)
        tmp = job.dir / "status.json.tmp"
        tmp.write_text(json.dumps(job.to_dict(), indent=2))
        tmp.replace(job.dir / "status.json")

    # -- api ----------------------------------------------------------------
    def create(self, raw: bytes, filename: str | None = None) -> Job:
        now = time.time()
        job = Job(id=uuid.uuid4().hex[:12], created=now, updated=now,
                  src={"filename": filename, "bytes": len(raw)})
        job.dir.mkdir(parents=True, exist_ok=True)
        (job.dir / "upload.bin").write_bytes(raw)
        with self._lock:
            self._jobs[job.id] = job
            self._persist(job)
        self._pool.submit(self._run, job.id)
        return job

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "running"
            self._persist(job)
        try:
            self._runner(job)
        except Exception as exc:  # noqa: BLE001 - report any failure to the user
            self.fail(job_id, str(exc))
        else:
            with self._lock:
                job.status = "done"
                job.stage = "done"
                job.progress = 1.0
                job.message = "Done"
                job.updated = time.time()
                self._persist(job)

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        with self._lock:
            return sorted(self._jobs.values(), key=lambda j: j.created, reverse=True)

    # -- mutations used by the runner --------------------------------------
    def update(self, job_id: str, **fields) -> Job:
        with self._lock:
            job = self._jobs[job_id]
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated = time.time()
            self._persist(job)
            return job

    def log(self, job_id: str, line: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.logs.append(line.rstrip())
            job.logs = job.logs[-400:]
            job.updated = time.time()
            self._persist(job)

    def advance(self, job_id: str, stage: str, message: str | None = None) -> None:
        idx = STAGE_INDEX.get(stage, 0)
        self.update(job_id, stage=stage, progress=STAGES[idx][1],
                    message=message or STAGES[idx][2])

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "failed"
            job.error = error
            job.message = "Failed"
            job.updated = time.time()
            self._persist(job)
