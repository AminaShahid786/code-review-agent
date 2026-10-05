import ast
import subprocess
import tempfile
import os
import re


def strip_code_fences(text: str) -> str:
    match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return match.group(1).strip() if match else text.strip()


def normalize(code: str) -> str:
    """Exactly one trailing newline. Used both here and by the agent loop's own
    static_analysis call, so 'missing-final-newline' either appears consistently
    everywhere or nowhere -- it can never be silently unconfirmable."""
    return code.rstrip() + "\n"


def _definition_names(code: str) -> set:
    """Names of all functions and classes defined in the code."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return set()
    return {
        n.name for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }


def apply_and_test(
    original_code: str,
    patched_code: str,
    test_dir: str = None,
    target_issue=None,
) -> dict:
    """
    Accepts a patch only if it is real, safe, and actually improves the code.

    target_issue: the issue the patch was meant to fix. If it is a dict with a
    'symbol', the patch is rejected when that issue is still present afterwards.
    Even without a target, a patch must reduce the number of static-analysis
    findings (when the original has any), so a rewrite that changes nothing
    that matters cannot be accepted.
    """
    from tools.analysis import is_syntax_valid, static_analysis

    patched_code = strip_code_fences(patched_code)

    # Check 1: syntax must still be valid
    if not is_syntax_valid(patched_code):
        return {"status": "REJECTED", "reason": "syntax_error"}

    # Check 2: the patch must actually change something
    if patched_code.strip() == original_code.strip():
        return {
            "status": "REJECTED",
            "reason": "no_change",
            "detail": "Patched code is identical to original — no fix was actually applied.",
        }

    # Check 3: no function or class may be removed or renamed
    missing = _definition_names(original_code) - _definition_names(patched_code)
    if missing:
        return {
            "status": "REJECTED",
            "reason": "definition_removed",
            "detail": f"Functions/classes removed or renamed: {sorted(missing)}",
        }

    # Check 4: static analysis before vs after
    try:
        before = static_analysis(normalize(original_code))
        after = static_analysis(normalize(patched_code))
    except Exception as e:
        return {"status": "REJECTED", "reason": "analysis_failed", "detail": str(e)}

    target_symbol = target_issue.get("symbol") if isinstance(target_issue, dict) else None
    if target_symbol and any(i.get("symbol") == target_symbol for i in after):
        return {
            "status": "REJECTED",
            "reason": "issue_not_fixed",
            "detail": f"Issue '{target_symbol}' still present after patch.",
        }

    if before and len(after) >= len(before):
        return {
            "status": "REJECTED",
            "reason": "no_improvement",
            "detail": f"Static-analysis findings did not decrease ({len(before)} before, {len(after)} after).",
        }

    # Check 5: run tests if a test_dir was provided
    if test_dir:
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "module.py")
            with open(target, "w") as f:
                f.write(patched_code)
            result = subprocess.run(
                ["pytest", test_dir, "--timeout=10"],
                capture_output=True, text=True, cwd=tmp,
            )
            if result.returncode != 0:
                return {"status": "REJECTED", "reason": "tests_failed", "detail": result.stdout[-500:]}

    return {"status": "ACCEPTED"}