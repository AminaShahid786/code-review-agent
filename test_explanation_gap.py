"""Bug 2 regression test: the final explanation said "No changes were made" for a
diff that clearly re-indented two lines. Uses the real diff and explanation from
review 4ffdac0b9e39 and a scripted fake model, so no Ollama is needed.
    python test_explanation_gap.py
"""
import json

from agent.report import check_explanation, generate_report

REAL = json.load(open("tests/fixtures/review_4ffdac0b9e39.json", encoding="utf-8"))
DIFF = REAL["diff"]
HALLUCINATED = REAL["explanation"]  # "No changes were made to the code. ..."
FIXED_CODE = "def calc(a, b, c):\n    x = a + b\n    return x * c\n"
GOOD = ("The two lines inside calc were re-indented from 1 space to 4 spaces. "
        "The logic is unchanged.")
SUMMARY = {"original_code": REAL["code"], "final_patch": FIXED_CODE,
           "issues_found": REAL["issues_found"]}


def check(name, ok, detail=""):
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if detail:
        print(f"       {detail}")
    return ok


def scripted(*answers):
    """A fake model that gives these answers in order, and counts its calls."""
    answers = list(answers)
    def call_slm(prompt, model=None, temperature=0.2):
        call_slm.calls += 1
        return answers.pop(0)
    call_slm.calls = 0
    return call_slm


problems = check_explanation(HALLUCINATED, DIFF)
results = [
    check("1. The real hallucinated explanation is caught", bool(problems), problems),
    check("2. A correct explanation passes (incl. 'logic is unchanged')",
          check_explanation(GOOD, DIFF) == [], check_explanation(GOOD, DIFF)),
    check("3. Claiming docstrings were added to an indentation-only diff is caught",
          bool(check_explanation("Added a docstring to calc and fixed indentation.", DIFF))),
]

# Model gets it right first time: used as-is, only one call.
slm = scripted(GOOD)
r = generate_report(SUMMARY, slm)
results.append(check("4. Correct first answer is kept (1 model call)",
                     r["explanation"] == GOOD and r["explanation_source"] == "model"
                     and slm.calls == 1, f"{r['explanation_source']}, {slm.calls} call(s)"))

# The real failure: wrong first, then corrected on retry.
slm = scripted(HALLUCINATED, GOOD)
r = generate_report(SUMMARY, slm)
results.append(check("5. Hallucination -> retried -> corrected answer used",
                     r["explanation"] == GOOD and slm.calls == 2
                     and r["explanation_source"].startswith("model (retried"),
                     r["explanation_source"]))

# Wrong twice: fall back to an explanation built only from verified facts.
slm = scripted(HALLUCINATED, HALLUCINATED)
r = generate_report(SUMMARY, slm)
results.append(check("6. Wrong twice -> factual fallback, never 'No changes were made'",
                     r["explanation_source"].startswith("automatic")
                     and "No changes" not in r["explanation"]
                     and "bad indentation" in r["explanation"]
                     and check_explanation(r["explanation"], DIFF) == [],
                     r["explanation"]))

results.append(check("7. Fixed issues come from pylint: bad-indentation x2",
                     [(f["symbol"], f["count"]) for f in r["fixed_issues"]]
                     == [("bad-indentation", 2)], r["fixed_issues"]))

print(f"\n{sum(results)}/{len(results)} checks passed")
