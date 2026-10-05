"""Runs one review job using the existing, tested pipeline:
load files -> run_agent -> extract_summary -> generate_report.
Nothing here changes how the agent or the verifier work; it only feeds them
input and records progress for the API.
"""
import os
from pathlib import Path

from adapters.loader import load_local_repo, load_github_repo
from agent.loop import run_agent, extract_summary
from agent.report import generate_report
from api import jobs

MAX_ITER = 8
# Each file can take 15-40 minutes, so refuse huge folders/repos instead of
# silently starting a run that would take all night. Override with REVIEW_MAX_FILES.
MAX_FILES = int(os.environ.get("REVIEW_MAX_FILES", "10"))
# Folders that are never the user's own code.
SKIP_DIRS = {"venv", ".venv", "env", ".git", "site-packages", "__pycache__", "node_modules"}

# REVIEW_FAKE_LLM=1 swaps the model for an instant fake that always answers
# "finish". The pipeline still runs for real (pylint, finish guard, report), so
# the API can be tested in seconds. Never use it for real results.
FAKE_LLM = os.environ.get("REVIEW_FAKE_LLM") == "1"


def _fake_slm(prompt: str, model: str = None, temperature: float = 0.2) -> str:
    return "Fake model: nothing to do.\nAction: finish\nAction Input: {}"


def _real_slm():
    from agent.llm import call_slm  # imported lazily so fake mode doesn't need Ollama
    return call_slm


def load_files(request: dict) -> list[dict]:
    kind = request["source_type"]
    if kind == "code":
        return [{"source": "pasted", "filepath": request.get("filename") or "submitted.py",
                 "code": request["code"]}]
    if kind == "folder":
        files = load_local_repo(request["path"])
    elif kind == "github":
        files = load_github_repo(request["url"], branch=request.get("branch") or "main")
    else:
        raise ValueError(f"Unknown source_type: {kind}")
    return [f for f in files if not SKIP_DIRS & set(Path(f["filepath"]).parts)]


def run_review(job_id: str) -> None:
    job = jobs.get_job(job_id)
    base_slm = _fake_slm if FAKE_LLM else _real_slm()
    calls = {"n": 0}

    def call_slm(prompt, model=None, temperature=0.2):
        # Wrap the model so the API can show "model call #N" while a file is running.
        calls["n"] += 1
        jobs.update_progress(job_id, model_calls=calls["n"],
                             message=f"Waiting for model call #{calls['n']} ({model or 'default'})")
        return base_slm(prompt, model=model, temperature=temperature)

    jobs.update_progress(job_id, message="Loading files")
    files = load_files(job["request"])
    if not files:
        raise ValueError("No Python (.py) files found in the submission.")
    if len(files) > MAX_FILES:
        raise ValueError(f"Submission has {len(files)} Python files; the limit is {MAX_FILES} "
                         f"(each file can take 15-40 minutes). Submit a smaller folder.")
    jobs.update_progress(job_id, files_total=len(files))

    for index, f in enumerate(files):
        jobs.update_progress(job_id, current_file=f["filepath"],
                             message=f"Reviewing file {index + 1} of {len(files)}")
        state = run_agent(f["code"], call_slm, MAX_ITER)
        summary = extract_summary(state)
        report = generate_report(summary, call_slm)
        jobs.add_result(job_id, {
            "filepath": f["filepath"],
            "original_code": summary["original_code"],
            "issues_found": report["bugs_found"],
            "remaining_issues": state.get("issues") or [],
            "corrected_code": report["corrected_code"],
            "diff": report["diff"],
            "explanation": report["explanation"],
            "explanation_source": report["explanation_source"],
            "explanation_problems": report["explanation_problems"],
            "fixed_issues": report["fixed_issues"],
            "verified_fix": report["corrected_code"] is not None,
            "history": state["history"],
        })
        jobs.update_progress(job_id, files_done=index + 1)

    jobs.update_progress(job_id, current_file=None)
