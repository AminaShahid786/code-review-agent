"""Bug 1 regression test: the model's malformed Action Input made the verifier check
the WRONG issue. Uses the real model output from review 4ffdac0b9e39 and a scripted
fake model, so no Ollama is needed. Runs in about 30 seconds (pylint calls).
    python test_parse_gap.py
"""
import json

from agent.loop import _resolve_issue, run_agent
from agent.parser import parse_react_output, unwrap_raw
from agent.prompts import build_prompt

REAL = json.load(open("tests/fixtures/review_4ffdac0b9e39.json", encoding="utf-8"))
HISTORY = REAL["history"]
# What the model actually typed after "Action Input:" (the old parser saved it as _raw)
MODEL_TEXT = {i: h["action_input"]["_raw"] for i, h in enumerate(HISTORY)
              if "_raw" in h["action_input"]}

KNOWN = REAL["issues_found"]  # bad-indentation x2, missing-module/function-docstring
DOCSTRINGS_ONLY = [k for k in KNOWN if k["symbol"] != "bad-indentation"]


def check(name, got, expected):
    ok = got == expected
    print(f"[{'PASS' if ok else 'FAIL'}] {name}")
    if not ok:
        print(f"       expected {expected!r}\n       got      {got!r}")
    return ok


def issue_symbol(step):
    """Parse step N's real model output with the fixed parser -> the issue symbol."""
    parsed = parse_react_output(f"Thought: x\nAction: propose_patch\nAction Input: {MODEL_TEXT[step]}")
    return (parsed["action_input"].get("issue") or {}).get("symbol")


results = [
    # --- the source of the problem: prompt history -------------------------------
    check("1. Prompt history shows past Action Inputs as valid JSON (double quotes)",
          all(json.loads(line[len("Action Input: "):]) is not None
              for line in build_prompt({"code": REAL["code"], "history": [
                  {"thought": "t", "action": "propose_patch",
                   "action_input": {"issue": KNOWN[3]}, "observation": "o"}]}).splitlines()
              if line.startswith("Action Input: {")),
          True),
    check("2. Parser reads a single-quoted Python dict (the model's usual format)",
          parse_react_output("Thought: x\nAction: propose_patch\n"
                             "Action Input: {'issue': {'symbol': 'bad-indentation', 'line': 2}}")
          ["action_input"],
          {"issue": {"symbol": "bad-indentation", "line": 2}}),
    # --- the real nested _raw inputs from review 4ffdac0b9e39 --------------------
    check("3. Real step 1 (1 layer) -> bad-indentation", issue_symbol(1), "bad-indentation"),
    check("4. Real step 2 (2 layers) -> missing-module-docstring",
          issue_symbol(2), "missing-module-docstring"),
    check("5. Real step 3 (3 layers) -> missing-function-docstring",
          issue_symbol(3), "missing-function-docstring"),
    check("6. Real step 7 (4 layers, code inside) -> missing-function-docstring",
          issue_symbol(7), "missing-function-docstring"),
    check("7. Old saved {'_raw': ...} inputs are unwrapped too",
          unwrap_raw(HISTORY[3]["action_input"])["issue"]["symbol"],
          "missing-function-docstring"),
    # --- _resolve_issue: what actually gets passed to the verifier ---------------
    check("8. Real step 3 input resolves to missing-function-docstring "
          "(old code picked bad-indentation)",
          # same path as execute_tool: unwrap the whole input, then take "issue"
          _resolve_issue(unwrap_raw(HISTORY[3]["action_input"]).get("issue", {}),
                         KNOWN)["symbol"],
          "missing-function-docstring"),
    check("9. An already-fixed symbol is not trusted; the Thought decides instead",
          _resolve_issue({"symbol": "bad-indentation", "line": 2}, DOCSTRINGS_ONLY,
                         "Now, I will address the missing function docstring.")["symbol"],
          "missing-function-docstring"),
    check("10. Unreadable input falls back to the issue named in the Thought",
          _resolve_issue({"_raw": "{not json at all"}, KNOWN,
                         "I will address the missing module docstring")["symbol"],
          "missing-module-docstring"),
]

# --- 11. Replay the exact failure end to end with a scripted model ----------------
# The model asks (in its real 3-layer format) to fix the function docstring; the
# patch model returns code that only fixes indentation. Before the fix this was
# ACCEPTED against the wrong target (bad-indentation). Now it must be rejected.
INDENT_ONLY = "def calc(a, b, c):\n    x = a + b\n    return x * c\n"
agent_script = iter([
    "Run analysis first.\nAction: static_analysis\nAction Input: {}",
    "Now, I will address the missing function docstring.\nAction: propose_patch\n"
    f"Action Input: {MODEL_TEXT[3]}",
    "Apply it.\nAction: apply_and_test\nAction Input: {}",
])


def scripted_slm(prompt, model=None, temperature=0.2):
    if model == "qwen-refactor-7b":  # the agent
        return next(agent_script, "Done.\nAction: finish\nAction Input: {}")
    return INDENT_ONLY  # the patch model


state = run_agent(REAL["code"], scripted_slm, max_iter=6)
apply_step = next(h for h in state["history"] if h["action"] == "apply_and_test")
results.append(check("11. Replay: patch that only fixes indentation is REJECTED as "
                     "issue_not_fixed for missing-function-docstring",
                     ("REJECTED" in apply_step["observation"],
                      "issue_not_fixed" in apply_step["observation"],
                      "missing-function-docstring" in apply_step["observation"]),
                     (True, True, True)))
print(f"       observation: {apply_step['observation']}")

print(f"\n{sum(results)}/{len(results)} checks passed")
