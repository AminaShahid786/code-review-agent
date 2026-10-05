"""Phase 3 test: the Streamlit page drives a real API server (fake model, temporary
database) through Streamlit's own headless test runner. No browser, no Ollama.
Takes about 30 seconds.
    python test_frontend.py
"""
import os
import subprocess
import sys
import tempfile
import time

import requests

sys.stdout.reconfigure(encoding="utf-8")  # emoji in check names on Windows

PORT = 8771
API = f"http://127.0.0.1:{PORT}"
os.environ["REVIEW_API_URL"] = API
CODE = "def calc(a, b, c):\n    x = a + b\n    return x * c\n"

from streamlit.testing.v1 import AppTest  # noqa: E402


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail and not ok:
        print(f"       {detail}")
    return ok


def page_text(at) -> str:
    parts = []
    for kind in ("markdown", "caption", "success", "info", "warning", "error", "code", "header", "subheader"):
        parts += [str(e.value) for e in getattr(at, kind)]
    return "\n".join(parts)


env = {**os.environ, "REVIEW_FAKE_LLM": "1",
       "REVIEW_DB": os.path.join(tempfile.mkdtemp(), "frontend_test.db")}
server = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.main:app", "--port", str(PORT)],
                          env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
results = []
try:
    for _ in range(30):
        try:
            requests.get(API + "/health", timeout=2)
            break
        except requests.ConnectionError:
            time.sleep(1)

    at = AppTest.from_file("frontend/app.py", default_timeout=30).run()
    results.append(check("1. Page loads with the submit form and no errors",
                         not at.exception and len(at.text_area) == 1
                         and "Start review" in [b.label for b in at.button],
                         [str(e) for e in at.exception]))

    at.text_area[0].input(CODE)
    at.run()
    start = next(b for b in at.button if b.label == "Start review")
    start.click().run()
    review_id = at.session_state.review_id
    # a double-click: the same button clicked again on the same page
    at2 = AppTest.from_file("frontend/app.py", default_timeout=30)
    at2.session_state.review_id = None
    at2.session_state.last_submit = at.session_state.last_submit
    at2.run()
    at2.text_area[0].input(CODE)
    at2.run()
    next(b for b in at2.button if b.label == "Start review").click().run()
    reviews = requests.get(API + "/reviews").json()
    results.append(check("2. Submitting creates one review; a quick second click opens it "
                         "instead of queueing a duplicate",
                         review_id and len(reviews) == 1
                         and at2.session_state.review_id == review_id,
                         f"{len(reviews)} review(s) created"))

    results.append(check("3. While the review is active, the page shows its live status",
                         any(s in page_text(at) for s in ("Queued", "Running", "Done"))
                         and not at.exception))

    for _ in range(60):
        if requests.get(f"{API}/reviews/{review_id}").json()["status"] not in ("queued", "running"):
            break
        time.sleep(1)
    at.run()
    text = page_text(at)
    results.append(check("4. Finished review shows original code, explanation and status",
                         "Finished in" in text and CODE.strip() in text
                         and "No verified fix" in text and not at.exception,
                         text[:500]))

    ups = [b for b in at.button if b.label == "👍 Yes"]
    ups[0].click().run()
    fb = requests.get(f"{API}/reviews/{review_id}").json()["feedback"]
    results.append(check("5. 👍 is sent to POST /reviews/{id}/feedback with the file name",
                         len(fb) == 1 and fb[0]["rating"] == "up"
                         and fb[0]["filepath"] == "submitted.py", fb))
    results.append(check("6. After rating, the buttons are replaced by a thank-you "
                         "(no second rating possible from a double-click)",
                         "👍 Yes" not in [b.label for b in at.button]
                         and "your 👍 was saved" in page_text(at)))

    at3 = AppTest.from_file("frontend/app.py", default_timeout=30)
    at3.query_params["review"] = review_id
    at3.run()
    results.append(check("7. Opening ?review=<id> (refresh/bookmark) shows that review",
                         at3.session_state.review_id == review_id
                         and "Finished in" in page_text(at3) and not at3.exception))
finally:
    server.terminate()

print(f"\n{sum(results)}/{len(results)} checks passed")
