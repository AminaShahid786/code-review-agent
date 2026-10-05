"""Runs the real model through propose_patch + apply_and_test on the calc example.
Much faster than the full agent loop: one or two model calls per issue."""
from agent.llm import call_slm
from tools.patcher import propose_patch
from sandbox.verify import apply_and_test

CODE = '''def calc(a, b, c):
    x = a + b
    y = x * c
    return y
'''

ISSUES = [
    {"line": 2, "type": "convention",
     "message": "Missing function or method docstring",
     "symbol": "missing-function-docstring"},
    {"line": 1, "type": "convention",
     "message": "Missing module docstring",
     "symbol": "missing-module-docstring"},
]

code = CODE
for issue in ISSUES:
    print(f"\n=== Fixing: {issue['symbol']} ===")
    patched = propose_patch(code, issue, call_slm)
    result = apply_and_test(code, patched, target_issue=issue)
    print(f"Verifier: {result}")
    if result["status"] == "ACCEPTED":
        code = patched

print("\n=== FINAL CODE ===")
print(code)
