"""FastAPI backend for the code review agent.

Run from the project root, with the venv activated (pylint must be on PATH):
    uvicorn api.main:app --port 8000
Interactive docs: http://127.0.0.1:8000/docs
Results are stored in reviews.db (SQLite) in the project root; REVIEW_DB overrides it.
"""
import os
import shutil
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, model_validator

from api import jobs
from api.runner import FAKE_LLM, run_review

@asynccontextmanager
async def lifespan(app: FastAPI):
    jobs.init()  # create/open reviews.db, close out interrupted reviews, start the worker
    yield


app = FastAPI(title="AI Code Review Agent", version="0.1", lifespan=lifespan)


class ReviewRequest(BaseModel):
    source_type: Literal["code", "folder", "github"]
    code: str | None = None       # source_type="code"
    filename: str | None = None   # optional label for pasted code
    path: str | None = None       # source_type="folder": a folder on this laptop
    url: str | None = None        # source_type="github"
    branch: str | None = "main"

    @model_validator(mode="after")
    def check_fields(self):
        needed = {"code": "code", "folder": "path", "github": "url"}[self.source_type]
        if not getattr(self, needed):
            raise ValueError(f"source_type '{self.source_type}' needs the '{needed}' field")
        if self.source_type == "github" and not self.url.startswith(("https://", "http://")):
            raise ValueError("url must start with https://")
        return self


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    filepath: str | None = None   # which file's fix this is about (None = whole review)
    comment: str | None = None


def _queue_review(request: dict) -> dict:
    if not jobs.worker_status()["alive"]:
        raise HTTPException(503, "Review worker is not running - restart the server "
                                 "and check its terminal for the error")
    job = jobs.create_job(request)
    jobs.submit(job["id"], run_review)
    return {"id": job["id"], "status": job["status"],
            "poll_url": f"/reviews/{job['id']}"}


@app.get("/health")
def health():
    """Quick check that the tools the agent needs are available."""
    ollama_ok = None
    if not FAKE_LLM:
        try:
            import ollama
            ollama.list()
            ollama_ok = True
        except Exception:
            ollama_ok = False
    return {"pylint_on_path": shutil.which("pylint") is not None,
            "ollama_running": ollama_ok,
            "fake_llm": FAKE_LLM,
            "worker": jobs.worker_status()}


@app.post("/reviews", status_code=202)
def create_review(req: ReviewRequest):
    """Start a review. Returns immediately with a job id; poll GET /reviews/{id}."""
    if req.source_type == "folder" and not os.path.isdir(req.path):
        raise HTTPException(400, f"Folder not found on this machine: {req.path}")
    return _queue_review(req.model_dump())


@app.post("/reviews/upload", status_code=202)
async def create_review_from_file(file: UploadFile = File(...), filename: str = Form(None)):
    """Start a review of one uploaded .py file (multipart form upload)."""
    name = filename or file.filename or "uploaded.py"
    if not name.endswith(".py"):
        raise HTTPException(400, "Only .py files are supported")
    try:
        code = (await file.read()).decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(400, "File is not valid UTF-8 text")
    return _queue_review({"source_type": "code", "code": code, "filename": name})


@app.get("/reviews")
def list_reviews():
    """All reviews, newest first (without per-file results, to keep it small)."""
    return [{k: j[k] for k in ("id", "status", "progress", "queue_position",
                               "created_at", "finished_at", "error")}
            for j in jobs.list_jobs()]


@app.get("/reviews/{review_id}")
def get_review(review_id: str):
    """Status, live progress, and (as each file finishes) its results."""
    job = jobs.get_job(review_id)
    if job is None:
        raise HTTPException(404, "Review not found")
    return job


@app.post("/reviews/{review_id}/feedback", status_code=201)
def add_feedback(review_id: str, fb: FeedbackRequest):
    """Store a thumbs up / thumbs down on a review (or on one file in it)."""
    entry = jobs.add_feedback(review_id, fb.model_dump())
    if entry is None:
        raise HTTPException(404, "Review not found")
    return entry
