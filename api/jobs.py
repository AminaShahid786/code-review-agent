"""Job store and background worker for reviews.

A review takes 15-40 minutes, so the API never waits for it: POST /reviews creates
a job here and returns at once; a background worker runs it; GET /reviews/{id}
reads its progress.

Jobs run ONE AT A TIME on a single worker thread, on purpose:
  - tools/analysis.py writes every check to the same temp.py, so two reviews at
    once would overwrite each other's file and give wrong results;
  - the laptop can only run one CPU model call at a time anyway.
Extra submissions wait in the queue with status "queued"; a queued job shows
which job it is waiting for ("waiting_for").

The worker is a daemon thread so Ctrl+C stops the server at once (any review in
progress is abandoned) instead of hanging until the current model call ends.

Reviews, per-file results (patches), findings and feedback are stored in SQLite
(api/db.py), so they survive a restart. Only the queue itself lives in memory: a
review left "queued" or "running" by a previous server process is marked failed
at startup, since nothing will run it any more.
"""
import logging
import queue
import threading
import time
import uuid
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import select, text

from api.db import Feedback, Finding, Patch, Review, Session, init_db

log = logging.getLogger("uvicorn.error")  # shows up in the uvicorn terminal

_waiting: list[str] = []  # ids of queued jobs, oldest first
_current: str | None = None  # id of the job the worker is running
_lock = threading.Lock()  # guards _waiting and _current
_work_queue: "queue.Queue[tuple[str, object]]" = queue.Queue()
_worker: threading.Thread | None = None

INTERRUPTED = "Interrupted: the server stopped before this review finished. Submit it again."


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init() -> None:
    """Create the tables, close out reviews a previous server left unfinished, and
    start the worker. Called once at server startup."""
    init_db()
    with Session.begin() as s:
        stale = s.scalars(select(Review).where(Review.status.in_(("queued", "running")))).all()
        for r in stale:
            r.status, r.error, r.finished_at = "failed", INTERRUPTED, _now()
            r.progress = {**r.progress, "message": "Interrupted"}
    if stale:
        log.warning("Marked %d unfinished review(s) from a previous run as failed: %s",
                    len(stale), ", ".join(r.id for r in stale))
    start_worker()


# ---------- converting rows to the JSON the API returns ----------------------------

def _finding_dict(f: Finding) -> dict:
    return {"line": f.line, "type": f.type, "message": f.message, "symbol": f.symbol,
            "fixed": f.fixed}


def _patch_dict(p: Patch) -> dict:
    return {
        "filepath": p.filepath,
        "original_code": p.original_code,
        "issues_found": [_finding_dict(f) for f in p.findings],
        "remaining_issues": p.remaining_issues,
        "corrected_code": p.corrected_code,
        "diff": p.diff,
        "explanation": p.explanation,
        "explanation_source": p.explanation_source,
        "explanation_problems": p.explanation_problems,
        "fixed_issues": p.fixed_issues,
        "verified_fix": p.verified_fix,
        "history": p.history,
    }


def _review_dict(r: Review, with_results: bool = True) -> dict:
    job = {
        "id": r.id, "status": r.status, "request": r.request,
        "progress": dict(r.progress), "error": r.error,
        "created_at": r.created_at, "started_at": r.started_at, "finished_at": r.finished_at,
    }
    if with_results:
        job["results"] = [_patch_dict(p) for p in r.patches]
        job["feedback"] = [{"rating": f.rating, "filepath": f.filepath,
                            "comment": f.comment, "created_at": f.created_at}
                           for f in r.feedback]
    # queue state is in memory, not in the database
    with _lock:
        if r.id in _waiting:
            ahead = _waiting.index(r.id) + (1 if _current else 0)
            job["queue_position"] = ahead + 1  # 1 = next to start
            job["waiting_for"] = _current or (_waiting[0] if ahead else None)
            job["progress"]["message"] = (
                f"Waiting for {ahead} earlier review(s) to finish (running now: {_current})"
                if ahead else "Starting")
        else:
            job["queue_position"] = None
            job["waiting_for"] = None
    return job


# ---------- the functions main.py and runner.py use --------------------------------

def create_job(request: dict) -> dict:
    job_id = uuid.uuid4().hex[:12]
    with Session.begin() as s:
        s.add(Review(id=job_id, status="queued", source_type=request["source_type"],
                     request=request, created_at=_now(),
                     progress={"message": "Queued", "files_total": 0, "files_done": 0,
                               "current_file": None, "model_calls": 0}))
    with _lock:
        _waiting.append(job_id)
    return get_job(job_id)


def get_job(job_id: str) -> dict | None:
    with Session() as s:
        r = s.get(Review, job_id)
        return _review_dict(r) if r else None


def list_jobs() -> list[dict]:
    """All reviews, newest first, without per-file results."""
    with Session() as s:
        rows = s.scalars(select(Review).order_by(text("reviews.rowid DESC"))).all()
        return [_review_dict(r, with_results=False) for r in rows]


def update_progress(job_id: str, **fields) -> None:
    with Session.begin() as s:
        r = s.get(Review, job_id)
        r.progress = {**r.progress, **fields}  # reassign: JSON columns don't track edits


def add_result(job_id: str, result: dict) -> None:
    """Store one file's result: a patches row plus one findings row per original issue."""
    # Mark each original finding fixed unless pylint still reports that rule afterwards.
    # Matched by rule, not line: fixes move lines (e.g. an added module docstring).
    still_open = Counter(i.get("symbol") for i in result.get("remaining_issues") or [])
    with Session.begin() as s:
        patch = Patch(review_id=job_id, filepath=result["filepath"],
                      original_code=result["original_code"],
                      corrected_code=result["corrected_code"], diff=result["diff"],
                      explanation=result["explanation"],
                      explanation_source=result.get("explanation_source"),
                      explanation_problems=result.get("explanation_problems") or [],
                      fixed_issues=result.get("fixed_issues") or [],
                      remaining_issues=result.get("remaining_issues") or [],
                      verified_fix=result["verified_fix"],
                      history=result.get("history") or [])
        for issue in result.get("issues_found") or []:
            symbol = issue.get("symbol")
            fixed = still_open[symbol] == 0
            if not fixed:
                still_open[symbol] -= 1
            patch.findings.append(Finding(review_id=job_id, line=issue.get("line"),
                                          type=issue.get("type"), symbol=symbol,
                                          message=issue.get("message"), fixed=fixed))
        s.add(patch)


def add_feedback(job_id: str, feedback: dict) -> dict | None:
    with Session.begin() as s:
        if s.get(Review, job_id) is None:
            return None
        entry = Feedback(review_id=job_id, rating=feedback["rating"],
                         filepath=feedback.get("filepath"), comment=feedback.get("comment"),
                         created_at=_now())
        s.add(entry)
        return {"rating": entry.rating, "filepath": entry.filepath,
                "comment": entry.comment, "created_at": entry.created_at}


# ---------- the background worker --------------------------------------------------

def submit(job_id: str, work) -> None:
    """Queue work(job_id) for the background worker."""
    _work_queue.put((job_id, work))


def start_worker() -> None:
    """Start the single background worker (called once at server startup)."""
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    _worker = threading.Thread(target=_worker_loop, name="review-worker", daemon=True)
    _worker.start()


def worker_status() -> dict:
    with _lock:
        current = _current
        waiting = len(_waiting)
    started = None
    if current:
        with Session() as s:
            r = s.get(Review, current)
            started = r.started_at if r else None
    return {"alive": _worker is not None and _worker.is_alive(),
            "current_job": current, "current_job_started_at": started,
            "queued_jobs": waiting}


def _worker_loop() -> None:
    log.info("Review worker started (thread %s)", threading.current_thread().name)
    try:
        while True:
            job_id, work = _work_queue.get()
            try:
                _run(job_id, work)
            except Exception:  # bookkeeping bug: log it, keep the worker alive
                log.exception("Review worker: unexpected error handling job %s", job_id)
    finally:
        log.error("Review worker STOPPED - new reviews will not run until restart")


def _set_status(job_id: str, message: str, **fields) -> None:
    with Session.begin() as s:
        r = s.get(Review, job_id)
        for k, v in fields.items():
            setattr(r, k, v)
        r.progress = {**r.progress, "message": message}


def _run(job_id: str, work) -> None:
    global _current
    with _lock:
        _waiting.remove(job_id)
        _current = job_id
    _set_status(job_id, "Starting", status="running", started_at=_now())
    log.info("Review %s: started", job_id)
    start = time.time()
    try:
        work(job_id)
        status, error = "done", None
    except Exception as e:  # report the failure on the job instead of losing it
        log.exception("Review %s: failed", job_id)
        status, error = "failed", f"{type(e).__name__}: {e}"
    finally:
        with _lock:
            _current = None
    _set_status(job_id, "Finished" if status == "done" else "Failed",
                status=status, error=error, finished_at=_now())
    log.info("Review %s: %s after %.0fs", job_id, status, time.time() - start)
