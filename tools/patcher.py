import re

PATCH_MODEL = "qwen-baseline-7b"

# Concrete instructions for findings the model tends to dismiss as "no change needed".
FIX_HINTS = {
    "missing-module-docstring": (
        "Add a one-line docstring as the very first statement of the file, "
        "describing what the module does."
    ),
    "missing-function-docstring": (
        "Add a one-line docstring as the first statement inside the function, "
        "describing what it does."
    ),
    "missing-class-docstring": (
        "Add a one-line docstring as the first statement inside the class, "
        "describing what it is for."
    ),
    "bad-indentation": "Re-indent the code using 4 spaces per indentation level.",
    "unused-import": "Remove the unused import line.",
    "unused-variable": "Remove the unused variable, or use it if it was clearly intended.",
    "line-too-long": "Wrap the long line so it fits within 100 characters.",
}


def _strip_fences(text: str) -> str:
    match = re.search(r"```(?:python)?\n(.*?)```", text, re.DOTALL)
    return (match.group(1) if match else text).strip()


def _describe_issue(issue):
    """Return (description, symbol) from a dict, a string, or anything else."""
    if isinstance(issue, dict):
        message = issue.get("message", "unspecified issue")
        line = issue.get("line", "unknown")
        return f"{message} (line {line})", issue.get("symbol")
    if isinstance(issue, str):
        symbol = next((s for s in FIX_HINTS if s in issue), None)
        return issue, symbol
    return "general code quality issue", None


def _build_prompt(code: str, desc: str, symbol, retry: bool) -> str:
    lines = [
        "You are fixing ONE static-analysis finding in Python code.",
        "",
        f"Finding: {desc}",
    ]
    if symbol:
        lines.append(f"Rule: {symbol}")
    hint = FIX_HINTS.get(symbol)
    if hint:
        lines.append(f"Required change: {hint}")
    lines += [
        "",
        "Rules:",
        "- The finding is real. Code that already runs can still need a change "
        "(style and documentation findings count). Never answer that no change is needed.",
        "- Change only what this finding requires. Keep behavior identical.",
        "- Do NOT rename or remove any function, class, or variable.",
        "- Return the complete corrected file only. No explanation. No markdown fences.",
    ]
    if retry:
        lines += [
            "",
            "Your previous answer was identical to the input code, which is wrong. "
            "The output MUST differ from the input by making the required change.",
        ]
    lines += ["", "Code:", "```python", code, "```"]
    return "\n".join(lines)


def propose_patch(code: str, issue, call_slm, max_attempts: int = 2) -> str:
    desc, symbol = _describe_issue(issue)
    patched = ""
    for attempt in range(max_attempts):
        prompt = _build_prompt(code, desc, symbol, retry=attempt > 0)
        raw = call_slm(prompt, model=PATCH_MODEL)
        patched = _strip_fences(raw)
        if patched and patched.strip() != code.strip():
            return patched
    # Still unchanged after retries: return it anyway so the verifier rejects it
    # with a clear reason, rather than hiding the failure here.
    return patched