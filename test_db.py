"""Phase 2 test: reviews are stored in SQLite and survive a server restart.
Uses a temporary database and the two real review results in tests/fixtures,
so no model is needed and reviews.db is not touched. Runs in a few seconds.
    python test_db.py
"""
import json
import os
import subprocess
import sys
import tempfile

os.environ["REVIEW_DB"] = os.path.join(tempfile.mkdtemp(), "test_reviews.db")
from api import jobs  # noqa: E402  (must come after REVIEW_DB is set)
from api.db import init_db  # noqa: E402


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail and not ok:
        print(f"       {detail}")
    return ok


def as_result(fixture_name):
    """Turn a saved real review into the result dict runner.py passes to add_result."""
    fx = json.load(open(f"tests/fixtures/{fixture_name}", encoding="utf-8"))
    return {"filepath": "submitted.py", "original_code": fx["code"],
            "issues_found": fx["issues_found"], "remaining_issues": fx["remaining_issues"],
            "corrected_code": fx.get("corrected_code"), "diff": fx["diff"],
            "explanation": fx["explanation"],
            "explanation_source": fx.get("explanation_source"),
            "explanation_problems": fx.get("explanation_problems", []),
            "fixed_issues": fx.get("fixed_issues", []),
            "verified_fix": fx.get("corrected_code") is not None or bool(fx["diff"]),
            "history": fx["history"]}


def in_new_process(code):
    """Run code in a fresh Python process on the same database = a server restart."""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         env=os.environ.copy())
    if out.returncode:
        print(out.stderr)
    return out.stdout.strip()


init_db()
results = []

# A finished review: the clean real run 2a1cbd019213 (both findings fixed)
clean = jobs.create_job({"source_type": "code", "code": "x"})["id"]
jobs._waiting.remove(clean)  # not handed to a worker in this test
real = as_result("review_2a1cbd019213.json")
jobs.add_result(clean, real)
jobs._set_status(clean, "Finished", status="done", finished_at=jobs._now())
jobs.add_feedback(clean, {"rating": "up", "filepath": "submitted.py", "comment": "correct"})
job = jobs.get_job(clean)
r = job["results"][0]
results += [
    check("1. Review, result and feedback round-trip through SQLite",
          job["status"] == "done" and r["corrected_code"] == real["corrected_code"]
          and r["history"] == real["history"] and job["feedback"][0]["rating"] == "up"),
    check("2. API result has the same keys as before (frontend contract unchanged)",
          set(r) == set(real), sorted(set(r) ^ set(real))),
    check("3. Findings stored one per row; both docstrings marked fixed",
          [(f["symbol"], f["fixed"]) for f in r["issues_found"]]
          == [("missing-module-docstring", True), ("missing-function-docstring", True)],
          r["issues_found"]),
]

# A partly fixed review: 4ffdac0b9e39 (indentation fixed, 2 docstrings still open)
partial = jobs.create_job({"source_type": "code", "code": "x"})["id"]
jobs._waiting.remove(partial)
jobs.add_result(partial, as_result("review_4ffdac0b9e39.json"))
flags = [(f["symbol"], f["fixed"]) for f in jobs.get_job(partial)["results"][0]["issues_found"]]
results.append(check("4. Partial fix: bad-indentation x2 fixed, docstrings still open",
                     flags == [("bad-indentation", True), ("bad-indentation", True),
                               ("missing-module-docstring", False),
                               ("missing-function-docstring", False)], flags))

# Leave one review queued and one running, as if the server were stopped mid-way
queued = jobs.create_job({"source_type": "code", "code": "x"})["id"]
running = jobs.create_job({"source_type": "code", "code": "x"})["id"]
jobs._set_status(running, "Waiting for model call #2", status="running", started_at=jobs._now())

# --- restart: a new process opens the same database ----------------------------------
after = json.loads(in_new_process(
    "import json; from api import jobs; jobs.init(); "
    f"print(json.dumps({{i: jobs.get_job(i) for i in {[clean, queued, running]!r}}}))"))
results += [
    check("5. After a restart the finished review and its feedback are still there",
          after[clean]["status"] == "done"
          and after[clean]["results"][0]["corrected_code"] == real["corrected_code"]
          and after[clean]["feedback"][0]["comment"] == "correct"),
    check("6. After a restart, unfinished reviews are marked failed (not stuck forever)",
          all(after[i]["status"] == "failed" and after[i]["error"] == jobs.INTERRUPTED
              for i in (queued, running)),
          {i: (after[i]["status"], after[i]["error"]) for i in (queued, running)}),
]

print(f"\n{sum(results)}/{len(results)} checks passed")
