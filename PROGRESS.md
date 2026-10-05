# Project Progress — AI-Driven Code Review and Refactoring Framework

_Last updated: 5 October 2026_

## 1. Component checklist

| Component (from proposal) | Status |
|---|---|
| Code collection (paste code, upload a file, local folder, GitHub repo) | ✅ Done |
| Static analysis (pylint finds real issues) | ✅ Done |
| SLM agent (local model proposes fixes step by step) | ✅ Done |
| Verification / testing (rejects fake or harmful fixes) | ✅ Done |
| Feedback report (issues, fixed code, diff, plain-English explanation) | ✅ Done |
| Backend (web API that runs reviews in the background) | ✅ Done |
| Database (save reviews, findings, fixes, feedback) | ✅ Done — SQLite file `reviews.db`; survives restarts |
| Frontend (web page to submit code and see results) | 🟡 In progress — built and tested automatically; first hands-on run in a browser still to do |
| Memory / feedback loop (👍/👎 collected and used later) | 🟡 In progress — 👍/👎 is saved permanently, but not used yet |

## 2. What currently works (plain language)

The system reads Python code — pasted in, uploaded as a file, taken from a folder, or
downloaded from GitHub — and checks it with a standard code-quality tool (pylint) to
find real problems. A small AI model running entirely on the laptop then suggests a fix
for each problem, one at a time. Every suggested fix is double-checked automatically:
it is thrown away if it changes nothing, deletes or renames any function, fails to fix
the problem it claimed to fix, or doesn't reduce the total number of problems. This
matters because the AI model was caught claiming to have fixed things it never changed.
Only fixes that pass this check are kept, and the system then writes a short
explanation of what changed — and that explanation is checked too: if it contradicts
the actual changes (for example, says "nothing was changed" when something was), it is
rewritten, and if the AI still gets it wrong, a plain factual summary is used instead. As of this week, all of this can be started through a
**web API**: you send code, immediately get back a ticket number, and can check that
ticket at any time to see live progress ("file 2 of 5, waiting for model call #3") and
the results. Reviews are handled one at a time in a queue, because a single review can
take 15–40 minutes on this laptop's CPU. Every review, every problem found (and whether
it was fixed), every fix and every 👍/👎 is saved in a small database file, so nothing
is lost when the server is restarted. A simple **web page** now sits on top of all this:
you paste or upload code, watch the review's progress live, then see the original and the
corrected code side by side, the exact changes, the explanation, and 👍/👎 buttons.

## 3. What's left (in order)

1. **Frontend:** first hands-on run in a browser with the real model; fix anything that
   feels unclear when used for real.
2. **Feedback loop:** use the stored 👍/👎 ratings (e.g. report which kinds of fixes users
   accept or reject).
3. Full end-to-end demo run with the real model through the web interface, recorded as
   evidence.
4. Report: Chapter 4 (Design) is drafted from the built system (architecture and
   agent-loop diagrams, verification algorithm) and is awaiting review.
5. Speed: the agent re-sends the whole code inside every step it remembers, which makes
   each model call slower as a review goes on. Worth trimming if time allows.

## 4. Evidence (real test results)

**Verifier catches a hallucinated fix** — full details in `verification_gap_evidence.md`.
Before the fix, the model returned unchanged code while claiming it had added
docstrings, and the old checker said `ACCEPTED`. After the fix:

```
[PASS] 1. Identical patch (the original bug) is rejected
[PASS] 2. Changed code that does NOT fix the issue is rejected
[PASS] 3. A real docstring fix is accepted
3/3 checks passed
```

**Backend API test (4 Oct 2026)** — run with the model replaced by an instant test stand-in
(`REVIEW_FAKE_LLM=1`) to check the API itself; static analysis and all safety checks ran for real.

- Three reviews submitted at once → first one started, the other two waited in a queue
  (`"status":"queued"`) and ran one after another, as designed.
- Live progress while running:
  `"message": "Waiting for model call #3", "files_total": 5, "files_done": 1, "current_file": "sample_repos\\test_project\\buggy_math.py"`
- The stand-in model tried to stop immediately without fixing anything; the agent's
  "finish guard" refused, twice:
  `NOT FINISHED: static analysis still reports 2 issue(s): ['missing-module-docstring', 'missing-function-docstring']`
  and the report correctly said: `No verified fix was produced for this file.`
- Bad input rejected with clear messages, e.g. `Folder not found on this machine: nope`,
  `source_type 'github' needs the 'url' field`, `rating: Input should be 'up' or 'down'`.
- Feedback stored: `{"rating":"up","comment":"looks right","created_at":"2026-10-04T16:49:18+00:00"}`

**Bug found and fixed (4 Oct 2026): a review looked "stuck in the queue".**
A submitted review stayed at "queued" with no visible reason. Investigation (a snapshot
of the running server) showed the background worker was alive and busy finishing an
*earlier* review — but nothing on screen said so, which made it look broken. Also,
stopping the server with Ctrl+C did not really stop it: it kept running in the
background until the AI model finished its current answer. Fixes:
- A waiting review now says exactly what it is waiting for:
  `queued pos 2 waiting_for 0587a876181d | Waiting for 1 earlier review(s) to finish (running now: 0587a876181d)`
- The health check now shows the worker:
  `"worker":{"alive":true,"current_job":"0587a876181d","queued_jobs":2}`
- The server terminal logs each step: `Review worker started`, `Review ... started`,
  `Review ... done after 48s`, and a full error report if a review fails. A failing
  review no longer affects the reviews behind it (tested: a failed review was
  followed by a successful one).
- Ctrl+C now stops the server immediately (tested: exits in 1 second while a review is
  running, instead of waiting for the model). The unfinished review is abandoned.

**Live test with the real model (5 Oct 2026): two ~19-minute reviews ran back to back
through the API without problems — and revealed two correctness bugs, now fixed.**
Example: review `4ffdac0b9e39` of a 3-line function with 4 problems (bad indentation on
2 lines, missing module and function descriptions/"docstrings"). The full real result
is saved in `tests/fixtures/review_4ffdac0b9e39.json` and used by the tests below.

*Bug 1 — the checker was sometimes checking the wrong problem.* The AI must say which
problem it is fixing in a fixed format. Its messages were garbled, and got worse every
step: by step 3 it wrote `{'_raw': '{'_raw': "{'code': ..., 'issue': {...
'missing-function-docstring'}}"}'}` — the request wrapped inside itself three times.
The cause was in our own prompt: it showed the AI its earlier steps in a slightly
different format (Python style, single quotes) than the one it is asked to use (JSON,
double quotes), so the AI copied that, our reader could not read it, stored it as
unreadable text, showed *that* back to the AI, and the AI copied the wrapping again.
Because the request was unreadable, the checker fell back to the first problem on the
list. So when the AI said *"Now, I will address the missing function docstring"* and
produced code without any docstring, the checker tested "is the indentation fixed?"
instead, and answered `ACCEPTED`. Fixes:
- The prompt now shows earlier steps in proper JSON, with one example of the right format.
- The reader now understands the AI's single-quote format and unwraps any number of
  layers (tested on the real garbled messages: 1, 2, 3 and 4 layers all read correctly).
- The program only accepts a target problem that is still actually present; if the
  message cannot be read, it uses the problem the AI named in its own reasoning.
- The core safety checks themselves were not changed — only what they are given.

Replaying the real failure with a scripted stand-in model now gives the correct verdict:
```
[PASS] 11. Replay: patch that only fixes indentation is REJECTED as issue_not_fixed for missing-function-docstring
       observation: {'status': 'REJECTED', 'reason': 'issue_not_fixed', 'detail': "Issue 'missing-function-docstring' still present after patch."}
11/11 checks passed        (python test_parse_gap.py)
```

*Bug 2 — the final explanation could contradict the real changes.* Same review: the
changes clearly re-indented two lines, but the AI's explanation said: *"No changes were
made to the code ... The refactored code is identical to the original."* Fix: the
explanation is now checked against the actual changes, just like fixes are. It is
rejected if it claims nothing changed when something did, or mentions descriptions
(docstrings), imports or renames that are not in the changes. The AI then gets one more
try, told exactly what was wrong; if it is still wrong, the system writes a factual
summary from verified data instead. The AI is also now told which problems pylint
confirmed as fixed, so it has the facts up front. Each result records which of these
happened (`explanation_source`).
```
[PASS] 1. The real hallucinated explanation is caught
       ['It says the code was not changed, but the diff changes 2 line(s) and adds 2 line(s).']
[PASS] 5. Hallucination -> retried -> corrected answer used
[PASS] 6. Wrong twice -> factual fallback, never 'No changes were made'
       The fix removed 2 line(s) and added 2 line(s). Static analysis (pylint) confirms these issues are now fixed: bad indentation (2 places).
7/7 checks passed          (python test_explanation_gap.py)
```
The earlier verifier test still passes unchanged (`python test_verify_gap.py`: 8/8).
Limitation: the explanation check catches these specific kinds of false claim; it
cannot prove every sentence is true.

**First fully clean end-to-end run through the API after both fixes (5 Oct 2026, review
`2a1cbd019213`).** A small function with two missing descriptions ("docstrings") was
submitted through the web API with the real AI model. It took **634 seconds (about 10.5
minutes)** and 9 model calls. What happened, step by step:
1. The checker found 2 problems: no description for the file, none for the function.
2. The AI fixed the function description; the checker confirmed exactly that problem was
   gone and **accepted** it (`remaining_issues: ['missing-module-docstring']`).
3. The AI fixed the file description, building on the first fix; **accepted**
   (`remaining_issues: []`).
4. The AI said it was finished — and this time it really was: nothing was left, so no
   "you're not done yet" refusal was needed.
5. The explanation was correct on the first try, with no retry or fallback
   (`explanation_source: "model"`).

Final code, verified by pylint:
```python
"""This module contains utility functions for basic arithmetic operations."""

def calc(a, b, c):
    """Calculate the product of the sum of a and b with c."""
    x = a + b
    return x * c
```
Honest limits: this was an easier input than the one that exposed the bugs (no
indentation problems). The AI's messages were still partly garbled in 3 of 6 steps, but
only one layer deep instead of growing every step, and it did not affect the result,
because the system decides the target and the code itself rather than trusting the
AI's copy. Full details in `verification_gap_evidence.md`; saved result in
`tests/fixtures/review_2a1cbd019213.json`.

**Database added (5 Oct 2026): results now survive a restart.** Everything is saved in
one SQLite file, `reviews.db`, with four tables: reviews (one per submission), patches
(the final checked fix for each file), findings (each problem pylint found, marked fixed
or still open), and feedback (👍/👎). Tested by really stopping the server in the middle
of a review and starting it again:
```
before kill: A=done B=running 2 / 5
--- server killed mid-review; restarting
A: done | ... | feedback [{'rating': 'down', 'comment': 'no fix produced', ...}]
B: failed | Interrupted: the server stopped before this review finished. Submit it again. | partial results kept: 2 file(s)
WARNING:  Marked 1 unfinished review(s) from a previous run as failed: e70a11f390bf
```
The finished review and its feedback were still there. The interrupted one was clearly
marked as interrupted, with the 2 files it had finished kept, instead of looking "stuck".
Automated test using the two real reviews above: `python test_db.py` -> 6/6 checks passed
(includes: a partly fixed file correctly shows indentation fixed and docstrings still open).

**Phase 2 confirmed with the real AI model (5 Oct 2026) — final Phase 2 evidence.**
Review `1dacc89391fd` was run through the API with the real model (9 model calls; it ran
from 09:00:34 to 09:11:01 UTC, about 10.5 minutes, after waiting its turn behind two
earlier reviews in the queue). Both problems were fixed and verified. A 👍 was then
recorded on it, and the server was fully stopped and started again as a new process
(new process number 9152, started 14:36:13 local time, after the feedback was saved at
14:35). Afterwards, read straight from the database file:
```
review   ('1dacc89391fd', 'done', started '09:00:34', finished '09:11:01', model_calls 9)
patches  [('submitted.py', verified_fix=1, explanation_source='model')]
findings [('missing-module-docstring', fixed=1), ('missing-function-docstring', fixed=1)]
feedback [(1, 'up', 'real restart test', '09:35:26'), (2, 'up', 'real restart test', '09:35:29')]
```
Everything survived the restart. The two identical 👍 rows, 3 seconds apart, came from
a double-click on the button; harmless, but the web page (next step) will block it, and
will also block double-clicking "Submit", which would otherwise queue a duplicate review.

**Web page built (5 Oct 2026, Phase 3).** A Streamlit page (`frontend/app.py`) that only
talks to the existing API — it contains no review, checking or database logic of its own.
It lets you paste or upload a `.py` file, shows live progress (refreshing every 5
seconds), then shows the original and corrected code side by side, the diff, the
explanation (with a note on whether it passed the check first time), the list of problems
with ✅/❌, the agent's steps, and 👍/👎 buttons. It protects against double-clicks: the
same code submitted twice within 30 seconds opens the existing review instead of starting
a second 10-minute one, and each file can only be rated once per visit.

Automated test, driving the page against a real API server (test mode, separate database):
```
python test_frontend.py
[PASS] 2. Submitting creates one review; a quick second click opens it instead of queueing a duplicate
[PASS] 5. 👍 is sent to POST /reviews/{id}/feedback with the file name
[PASS] 6. After rating, the buttons are replaced by a thank-you (no second rating possible from a double-click)
[PASS] 7. Opening ?review=<id> (refresh/bookmark) shows that review
7/7 checks passed
```
The page was also pointed (read-only) at the real review `1dacc89391fd`; it showed
"Finished in 10 min 27 s with 9 model call(s)", "Verified fix: 2 of 2 issue(s) fixed and
confirmed by pylint", the two code versions side by side, and the diff.
