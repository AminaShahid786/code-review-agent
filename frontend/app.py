"""Streamlit frontend for the code review agent.

It only calls the existing API (api/main.py) - no review, verification or database
logic lives here. Start the API first, then this page, in two terminals:
    uvicorn api.main:app --port 8000
    streamlit run frontend/app.py
REVIEW_API_URL overrides the API address (default http://127.0.0.1:8000).
"""
import hashlib
import os
import time
from datetime import datetime, timezone

import requests
import streamlit as st  # type: ignore[import-not-found]

API = os.environ.get("REVIEW_API_URL", "http://127.0.0.1:8000").rstrip("/")
POLL_SECONDS = 5
RESUBMIT_GUARD_SECONDS = 30  # same code submitted again within this time = a double-click
ACTIVE = ("queued", "running")

st.set_page_config(page_title="AI Code Review", page_icon="🔍", layout="wide")


# ---------- talking to the API ------------------------------------------------------

def api(method: str, path: str, **kwargs):
    """Call the backend. Returns (json, None) or (None, an error message for the user)."""
    try:
        r = requests.request(method, API + path, timeout=15, **kwargs)
    except requests.ConnectionError:
        return None, f"Cannot reach the API at {API}. Is uvicorn running?"
    except requests.Timeout:
        return None, f"The API at {API} did not answer within 15 seconds."
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail", r.text)
        except ValueError:
            detail = r.text
        if isinstance(detail, list):  # FastAPI validation errors
            detail = "; ".join(d.get("msg", str(d)) for d in detail)
        return None, f"The API refused the request ({r.status_code}): {detail}"
    return r.json(), None


def open_review(review_id: str | None) -> None:
    st.session_state.review_id = review_id
    if review_id:
        st.query_params["review"] = review_id
    else:
        st.query_params.clear()


# ---------- small formatting helpers ------------------------------------------------

STATUS_LABEL = {"queued": ":blue[● Queued]", "running": ":orange[● Running]",
                "done": ":green[● Done]", "failed": ":red[● Failed]"}

EXPLANATION_SOURCE = {
    "model": "Written by the model, then checked against the diff: passed first time.",
    "model (retried after failed check)":
        "The model's first explanation contradicted the diff and was rejected; "
        "this second attempt passed the check.",
    "automatic (model explanation failed checks twice)":
        "Both model explanations contradicted the diff, so this summary was built "
        "only from verified facts (the diff and pylint).",
    "automatic": "The verified code differs only in whitespace, so no model explanation was needed.",
    "none": "No verified fix, so there is nothing to explain.",
}


def _parse_time(iso: str | None):
    return datetime.fromisoformat(iso) if iso else None


def _minutes(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60} min {seconds % 60:02d} s"


# ---------- sidebar: health and past reviews ---------------------------------------

def sidebar() -> None:
    st.sidebar.title("🔍 AI Code Review")
    health, err = api("GET", "/health")
    if err:
        st.sidebar.error(err)
    else:
        worker = health["worker"]
        st.sidebar.markdown(
            f"{'✅' if health['pylint_on_path'] else '❌'} pylint  \n"
            f"{'🧪 fake model (test mode)' if health['fake_llm'] else ('✅' if health['ollama_running'] else '❌') + ' Ollama'}  \n"
            f"{'✅' if worker['alive'] else '❌'} review worker"
            + (f" · busy with `{worker['current_job']}`" if worker["current_job"] else " · idle")
            + (f" · {worker['queued_jobs']} queued" if worker["queued_jobs"] else ""))
        if health["fake_llm"]:
            st.sidebar.warning("The API is in fake-model mode: results are not real reviews.")

    if st.sidebar.button("➕ New review", width="stretch"):
        open_review(None)
        st.rerun()

    reviews, err = api("GET", "/reviews")
    if reviews:
        st.sidebar.subheader("Past reviews")
        for r in reviews[:30]:
            created = _parse_time(r["created_at"]).astimezone().strftime("%d %b %H:%M")
            label = f"{STATUS_LABEL[r['status']]} `{r['id']}` · {created}"
            if st.sidebar.button(label, key=f"open-{r['id']}", width="stretch"):
                open_review(r["id"])
                st.rerun()


# ---------- submit page -------------------------------------------------------------

def _submit(mode: str) -> None:
    """Button callback: send the code to the API (at most once per double-click)."""
    if mode == "Paste code":
        code = st.session_state.get("paste_code", "")
        name = (st.session_state.get("paste_name") or "submitted.py").strip()
        payload = code.encode("utf-8")
    else:
        upload = st.session_state.get("upload_file")
        if upload is None:
            return
        name, payload = upload.name, upload.getvalue()
    if not payload.strip():
        st.session_state.flash = ("warning", "There is no code to review yet.")
        return

    fingerprint = hashlib.sha256(name.encode() + b"\0" + payload).hexdigest()
    last = st.session_state.get("last_submit")
    if last and last["fingerprint"] == fingerprint and time.time() - last["at"] < RESUBMIT_GUARD_SECONDS:
        open_review(last["id"])  # a double-click: show the review already queued
        return

    if mode == "Paste code":
        job, err = api("POST", "/reviews", json={"source_type": "code", "code": code,
                                                  "filename": name})
    else:
        job, err = api("POST", "/reviews/upload",
                       files={"file": (name, payload, "text/x-python")})
    if err:
        st.session_state.flash = ("error", err)
        return
    st.session_state.last_submit = {"fingerprint": fingerprint, "at": time.time(),
                                    "id": job["id"]}
    open_review(job["id"])


def submit_page() -> None:
    st.header("Review Python code")
    st.caption("The agent finds pylint issues, asks a local model for fixes, and keeps only "
               "fixes that a deterministic verifier confirms. On this laptop a single file "
               "usually takes 10-40 minutes.")
    mode = st.radio("Code source", ["Paste code", "Upload a .py file"], horizontal=True,
                    label_visibility="collapsed")
    if mode == "Paste code":
        st.text_input("File name (used as a label)", value="submitted.py", key="paste_name")
        st.text_area("Python code", height=320, key="paste_code",
                     placeholder="def calc(a, b, c):\n    x = a + b\n    return x * c")
        ready = bool(st.session_state.get("paste_code", "").strip())
    else:
        st.file_uploader("Python file", type=["py"], key="upload_file")
        ready = st.session_state.get("upload_file") is not None
    st.button("Start review", type="primary", disabled=not ready,
              on_click=_submit, args=(mode,))


# ---------- review page -------------------------------------------------------------

def render_status(job: dict) -> None:
    progress = job["progress"]
    st.markdown(f"### {STATUS_LABEL[job['status']]} &nbsp; Review `{job['id']}`")
    started, finished = _parse_time(job["started_at"]), _parse_time(job["finished_at"])

    if job["status"] == "queued":
        st.info(progress["message"]
                + (f" — position {job['queue_position']} in the queue" if job["queue_position"] else ""))
    elif job["status"] == "running":
        total, done = progress["files_total"], progress["files_done"]
        if total:
            st.progress(done / total, text=f"File {min(done + 1, total)} of {total}"
                        + (f": `{progress['current_file']}`" if progress["current_file"] else ""))
        elapsed = (datetime.now(timezone.utc) - started).total_seconds() if started else 0
        cols = st.columns(3)
        cols[0].metric("Now", progress["message"].split(" (")[0])
        cols[1].metric("Model calls so far", progress["model_calls"])
        cols[2].metric("Running for", _minutes(elapsed))
        st.caption(f"This page refreshes every {POLL_SECONDS} seconds. You can close it; "
                   "the review keeps running and stays in the list on the left.")
    elif job["status"] == "done":
        took = _minutes((finished - started).total_seconds()) if started and finished else "?"
        st.success(f"Finished in {took} with {progress['model_calls']} model call(s).")
    else:
        st.error(job["error"] or "The review failed.")


@st.fragment(run_every=POLL_SECONDS)
def live_status(review_id: str) -> None:
    """Re-polls GET /reviews/{id} while the review is active; reloads the page when done."""
    job, err = api("GET", f"/reviews/{review_id}")
    if err:
        st.error(err)
        return
    render_status(job)
    if job["status"] not in ACTIVE:
        st.rerun()  # whole page, so the results appear


def _send_feedback(review_id: str, filepath: str, rating: str) -> None:
    """Button callback: post one rating per file per session (ignores double-clicks)."""
    key = (review_id, filepath)
    sent = st.session_state.setdefault("feedback_sent", {})
    if key in sent:
        return
    sent[key] = rating  # set before the request, so a second click is ignored
    comment = st.session_state.get(f"comment-{review_id}-{filepath}") or None
    _, err = api("POST", f"/reviews/{review_id}/feedback",
                 json={"rating": rating, "filepath": filepath, "comment": comment})
    if err:
        del sent[key]
        st.session_state.flash = ("error", err)


def render_feedback(job: dict, result: dict) -> None:
    review_id, filepath = job["id"], result["filepath"]
    sent = st.session_state.get("feedback_sent", {}).get((review_id, filepath))
    earlier = [f for f in job["feedback"] if f["filepath"] == filepath]
    st.markdown("**Was this review useful?**")
    if sent:
        st.success(f"Thanks — your {'👍' if sent == 'up' else '👎'} was saved.")
        return
    if earlier:
        latest = earlier[-1]
        st.caption(f"Already rated {'👍' if latest['rating'] == 'up' else '👎'} "
                   f"({len(earlier)} rating(s) saved). You can add another.")
    st.text_input("Comment (optional)", key=f"comment-{review_id}-{filepath}")
    up, down, _ = st.columns([1, 1, 6])
    up.button("👍 Yes", key=f"up-{review_id}-{filepath}",
              on_click=_send_feedback, args=(review_id, filepath, "up"))
    down.button("👎 No", key=f"down-{review_id}-{filepath}",
                on_click=_send_feedback, args=(review_id, filepath, "down"))


def render_result(job: dict, result: dict) -> None:
    st.subheader(f"📄 {result['filepath']}")
    findings = result["issues_found"]
    fixed = sum(1 for f in findings if f.get("fixed"))
    if not findings:
        st.success("pylint found no issues in this file.")
    elif result["verified_fix"]:
        st.success(f"Verified fix: {fixed} of {len(findings)} issue(s) fixed and confirmed by pylint.")
    else:
        st.warning(f"No verified fix was produced. {len(findings)} issue(s) remain unfixed.")

    if findings:
        st.dataframe([{"Line": f["line"], "Rule": f["symbol"], "Message": f["message"],
                       "Fixed": "✅" if f.get("fixed") else "❌"} for f in findings],
                     hide_index=True, width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("**Original**")
        st.code(result["original_code"], language="python", line_numbers=True)
    with right:
        st.markdown("**Corrected (verified)**")
        if result["corrected_code"]:
            st.code(result["corrected_code"], language="python", line_numbers=True)
        else:
            st.info("No verified fix — the original code is unchanged.")

    if result["diff"]:
        st.markdown("**Diff**")
        st.code(result["diff"], language="diff")

    st.markdown("**Explanation**")
    st.markdown(result["explanation"] or "_No explanation._")
    st.caption(EXPLANATION_SOURCE.get(result.get("explanation_source"),
                                      result.get("explanation_source") or ""))
    if result.get("explanation_problems"):
        with st.expander("Why the first explanation was rejected"):
            for p in result["explanation_problems"]:
                st.markdown(f"- {p}")

    with st.expander(f"Agent steps ({len(result['history'])})"):
        st.dataframe([{"Step": i, "Action": h.get("action"), "Thought": h.get("thought"),
                       "Observation": str(h.get("observation"))[:300]}
                      for i, h in enumerate(result["history"])],
                     hide_index=True, width="stretch")

    render_feedback(job, result)


def review_page(review_id: str) -> None:
    job, err = api("GET", f"/reviews/{review_id}")
    if err:
        st.error(err)
        return
    if job["status"] in ACTIVE:
        live_status(review_id)
        return
    render_status(job)
    for result in job["results"]:
        st.divider()
        render_result(job, result)
    if job["status"] == "done" and not job["results"]:
        st.info("The review finished without any file results.")


# ---------- page --------------------------------------------------------------------

if "review_id" not in st.session_state:
    st.session_state.review_id = st.query_params.get("review")

sidebar()
if flash := st.session_state.pop("flash", None):
    getattr(st, flash[0])(flash[1])
if st.session_state.review_id:
    review_page(st.session_state.review_id)
else:
    submit_page()
