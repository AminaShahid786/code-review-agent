"""Deterministic test of sandbox/verify.py: no LLM involved, runs in seconds."""
from sandbox.verify import apply_and_test

ORIGINAL = '''def calc(a, b, c):
    x = a + b
    y = x * c
    return y
'''

# Code changed, but the flagged issue (missing docstring) is still there
RENAMED_VARS = '''def calc(a, b, c):
    total = a + b
    result = total * c
    return result
'''

# The exact patch the model produced in the live run: function AND variables
# renamed, no docstring anywhere, yet the model claimed it added one.
LIVE_RUN_FAKE = '''def calculate(a, b, c):
    intermediate_sum = a + b
    result = intermediate_sum * c
    return result
'''

# Docstrings added, but the function was renamed (breaks callers)
DOCSTRING_BUT_RENAMED = '''"""Utility math helpers."""


def calculate(a, b, c):
    """Return (a + b) * c."""
    x = a + b
    y = x * c
    return y
'''

# A real fix: module and function docstrings added
REAL_FIX = '''"""Utility math helpers."""


def calc(a, b, c):
    """Return (a + b) * c."""
    x = a + b
    y = x * c
    return y
'''

# Patch #2 from the second live run: module docstring added, function docstring
# still missing. A genuine partial fix that must be accepted.
PARTIAL_FIX = '''"""
This module contains a function to perform a calculation.
"""

def calc(a, b, c):
    x = a + b
    y = x * c
    return y
'''

TARGET = {"symbol": "missing-function-docstring", "line": 2}
NO_TARGET = {}  # what the model often sends


def check(name, result, expected_status, expected_reason=None):
    ok = result.get("status") == expected_status
    if expected_reason:
        ok = ok and result.get("reason") == expected_reason
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    print(f"       got {result}\n")
    return ok


results = [
    check("1. Identical patch is rejected",
          apply_and_test(ORIGINAL, ORIGINAL, target_issue=TARGET),
          "REJECTED", "no_change"),
    check("2. Changed code that does NOT fix the target issue is rejected",
          apply_and_test(ORIGINAL, RENAMED_VARS, target_issue=TARGET),
          "REJECTED", "issue_not_fixed"),
    check("3. A real docstring fix is accepted",
          apply_and_test(ORIGINAL, REAL_FIX, target_issue=TARGET),
          "ACCEPTED"),
    check("4. Variable renames with NO target issue are rejected (no improvement)",
          apply_and_test(ORIGINAL, RENAMED_VARS, target_issue=NO_TARGET),
          "REJECTED", "no_improvement"),
    check("5. The exact fake patch from the live run is rejected",
          apply_and_test(ORIGINAL, LIVE_RUN_FAKE, target_issue=NO_TARGET),
          "REJECTED", "definition_removed"),
    check("6. Docstrings added but function renamed is rejected",
          apply_and_test(ORIGINAL, DOCSTRING_BUT_RENAMED, target_issue=TARGET),
          "REJECTED", "definition_removed"),
    check("7. A real fix is accepted even when the model sends no target issue",
          apply_and_test(ORIGINAL, REAL_FIX, target_issue=NO_TARGET),
          "ACCEPTED"),
    check("8. Partial fix (module docstring only) is accepted for its own target",
          apply_and_test(ORIGINAL, PARTIAL_FIX,
                         target_issue={"symbol": "missing-module-docstring", "line": 1}),
          "ACCEPTED"),
]

print(f"{sum(results)}/{len(results)} checks passed")