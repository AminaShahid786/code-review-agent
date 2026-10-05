import difflib
import re
from collections import Counter

from sandbox.verify import strip_code_fences, normalize
from tools.analysis import static_analysis

# Claims that the code as a whole was not changed. Narrow on purpose: "the logic
# is unchanged" is a true statement about a formatting fix and must not match.
NO_CHANGE_CLAIM = re.compile(
    r"\bno (functional |actual )?changes? (was|were|has been|have been) made\b|"
    r"\bidentical to the original\b|\b(code|file) (is|was|remains) (identical|unchanged)\b|"
    r"\bnothing (was |has been )?changed\b", re.IGNORECASE)


def generate_diff(original: str, patched: str) -> str:
    diff = difflib.unified_diff(
        original.strip().splitlines(),
        patched.strip().splitlines(),
        fromfile="original",
        tofile="refactored",
        lineterm=""
    )
    return "\n".join(diff)


def _changed_lines(diff: str) -> tuple[list[str], list[str]]:
    """(added, removed) lines of a unified diff, without the +++/--- headers."""
    lines = diff.splitlines()
    added = [l[1:] for l in lines if l.startswith("+") and not l.startswith("+++")]
    removed = [l[1:] for l in lines if l.startswith("-") and not l.startswith("---")]
    return added, removed


def fixed_issues(before: list[dict], after: list[dict]) -> list[dict]:
    """Findings that static analysis reported before the fix and no longer reports."""
    gone = Counter(i.get("symbol") for i in before) - Counter(i.get("symbol") for i in after)
    messages = {i.get("symbol"): i.get("message") for i in before}
    return [{"symbol": s, "message": messages[s], "count": n} for s, n in gone.items()]


def check_explanation(explanation: str, diff: str) -> list[str]:
    """Return the claims in the explanation that the diff contradicts (empty = OK).
    Like apply_and_test for patches: the model's description is not trusted."""
    added, removed = _changed_lines(diff)
    changed = added + removed
    text = explanation or ""
    lower = text.lower()
    problems = []
    if not text.strip():
        problems.append("The explanation is empty.")
    if changed and NO_CHANGE_CLAIM.search(text):
        problems.append(f"It says the code was not changed, but the diff changes "
                        f"{len(removed)} line(s) and adds {len(added)} line(s).")
    if "docstring" in lower and not any('"""' in l or "'''" in l for l in changed):
        problems.append("It mentions docstrings, but no docstring was added or removed.")
    if re.search(r"\bimports?\b", lower) and not any(
            l.strip().startswith(("import ", "from ")) for l in changed):
        problems.append("It mentions imports, but no import line was changed.")
    if "renam" in lower:
        names_before = set(re.findall(r"[A-Za-z_]\w*", "\n".join(removed)))
        names_after = set(re.findall(r"[A-Za-z_]\w*", "\n".join(added)))
        if names_before == names_after:
            problems.append("It mentions renaming, but every name in the changed lines "
                            "is the same before and after.")
    return problems


def _describe_fixed(fixed: list[dict]) -> str:
    return "; ".join(f"{f['symbol']} ({f['message']}) x{f['count']}" for f in fixed)


def factual_explanation(diff: str, fixed: list[dict]) -> str:
    """An explanation built only from verified facts: used when the model's fails."""
    added, removed = _changed_lines(diff)
    text = f"The fix removed {len(removed)} line(s) and added {len(added)} line(s)."
    if fixed:
        names = ", ".join(f["symbol"].replace("-", " ")
                          + (f" ({f['count']} places)" if f["count"] > 1 else "")
                          for f in fixed)
        text += f" Static analysis (pylint) confirms these issues are now fixed: {names}."
    return text


def _explanation_prompt(diff: str, fixed: list[dict], problems: list[str] = None) -> str:
    prompt = f"""Below is a unified diff showing the exact changes made to a Python file.
Lines starting with "-" were removed. Lines starting with "+" were added. Unchanged lines have no prefix.

{diff}

Static analysis (pylint) confirms these issues were fixed by this diff: {_describe_fixed(fixed) or "none"}.

Write a short, accurate explanation (2-4 sentences) of ONLY the changes shown in this diff.
The diff is not empty, so the code WAS changed: describe what changed.
Do NOT mention any change that is not visibly present in the diff above.
Do NOT assume docstrings, imports, or renames were changed unless you can see them added or removed in the diff text itself."""
    if problems:
        prompt += ("\n\nA previous explanation was rejected because it was wrong:\n- "
                   + "\n- ".join(problems)
                   + "\nWrite a new explanation that avoids these mistakes.")
    return prompt


def generate_report(summary: dict, call_slm) -> dict:
    original = summary["original_code"]
    patch = summary["final_patch"]
    issues = summary["issues_found"]

    if not patch:
        return {
            "bugs_found": issues,
            "corrected_code": None,
            "diff": None,
            "explanation": "No verified fix was produced for this file.",
            "fixed_issues": [],
            "explanation_source": "none",
            "explanation_problems": [],
        }

    clean_patch = strip_code_fences(patch)
    diff = generate_diff(original, clean_patch)
    fixed = fixed_issues(issues, static_analysis(normalize(clean_patch)))
    first_problems = []

    if not diff.strip():
        explanation = "No functional changes were made to the code. It already followed best practices."
        source = "automatic"
    else:
        # Same idea as apply_and_test: check the model's claims, retry once with the
        # exact mistakes, and fall back to verified facts if it is still wrong.
        explanation = call_slm(_explanation_prompt(diff, fixed), model="qwen-baseline-7b")
        first_problems = check_explanation(explanation, diff)
        source = "model"
        if first_problems:
            explanation = call_slm(_explanation_prompt(diff, fixed, first_problems),
                                   model="qwen-baseline-7b")
            source = "model (retried after failed check)"
            if check_explanation(explanation, diff):
                explanation = factual_explanation(diff, fixed)
                source = "automatic (model explanation failed checks twice)"

    return {
        "bugs_found": issues,
        "corrected_code": clean_patch,
        "diff": diff,
        "explanation": explanation,
        "fixed_issues": fixed,
        "explanation_source": source,
        "explanation_problems": first_problems,
    }
