from agent.prompts import build_prompt
from agent.parser import parse_react_output, unwrap_raw
from tools.analysis import static_analysis
from tools.patcher import propose_patch
from sandbox.verify import apply_and_test, strip_code_fences, normalize

# How many times the loop may refuse a premature `finish` per file.
MAX_FINISH_NUDGES = 2


def _symbol_words(symbol: str) -> str:
    return (symbol or "").replace("-", " ").lower()


def _resolve_issue(issue, known_issues, thought: str = ""):
    """Map whatever the model sent to a real finding from static analysis.
    The model often sends an empty dict, a string, a re-stringified {"_raw": ...}
    wrapper, a wrong line number, or an issue that was already fixed, so the loop
    does not trust it: the target always comes from the current analysis results.
    Order: unwrapped issue dict -> line -> text match -> the model's own Thought
    -> first remaining issue (last resort)."""
    issue = unwrap_raw(issue)
    if not known_issues:
        return issue
    if isinstance(issue, dict) and issue.get("symbol"):
        same = [k for k in known_issues if k.get("symbol") == issue["symbol"]]
        if same:  # prefer the exact line, else any finding with that symbol
            return next((k for k in same if k.get("line") == issue.get("line")), same[0])
        # symbol not reported any more (already fixed, or invented): don't target it
    if isinstance(issue, dict) and issue.get("line") is not None and not issue.get("symbol"):
        for k in known_issues:
            if k.get("line") == issue.get("line"):
                return k
    if isinstance(issue, str):
        for k in known_issues:
            if k.get("symbol") in issue or k.get("message") in issue:
                return k
    # The Thought usually names the issue in words ("fix the missing function
    # docstring"). Longest symbol first, so "missing function docstring" wins
    # over a shorter symbol that happens to be contained in the text.
    text = (thought or "").lower().replace("-", " ")
    for k in sorted(known_issues, key=lambda k: -len(k.get("symbol") or "")):
        if _symbol_words(k.get("symbol")) and _symbol_words(k.get("symbol")) in text:
            return k
    return known_issues[0]


def execute_tool(action: str, action_input: dict, state: dict, call_slm) -> str:
    code = state["code"]
    action_input = unwrap_raw(action_input)
    if not isinstance(action_input, dict):
        action_input = {}

    if action == "static_analysis":
        code = normalize(code)
        state["issues"] = static_analysis(code)
        return str(state["issues"])

    elif action == "propose_patch":
        if not state.get("issues"):
            state["issues"] = static_analysis(code)
        issue = _resolve_issue(action_input.get("issue", {}), state["issues"],
                               state.get("last_thought", ""))
        state["last_issue"] = issue  # remember what this patch is meant to fix
        patch = propose_patch(code, issue, call_slm)
        state["last_patch"] = patch  # remember the patch itself
        return patch

    elif action == "apply_and_test":
        # Verify the patch the patcher actually produced. The model often does not
        # re-type the whole file correctly (or at all), so it is only a fallback.
        patched = state.get("last_patch") or action_input.get("patched_code") or code
        result = apply_and_test(code, patched, target_issue=state.get("last_issue"))
        if result.get("status") == "ACCEPTED":
            # Build on the accepted fix so the next patch starts from it, and tell
            # the model what is still left instead of letting it guess.
            state["code"] = normalize(strip_code_fences(patched))
            state["issues"] = static_analysis(state["code"])
            state["last_patch"] = None
            result["remaining_issues"] = [i.get("symbol") for i in state["issues"]]
        return str(result)

    else:
        return f"Unknown action: {action}"


def run_agent(code: str, call_slm, max_iter: int = 8) -> dict:
    # Whitespace-only findings (e.g. missing final newline) are fixed here, not by the
    # model: a patch that only adds "\n" is invisible to the verifier's no-change check,
    # so the agent could never "fix" it. Report them as found, apply the fix up front.
    initial_issues = static_analysis(code)
    prepared = code.rstrip() + "\n"
    prepared_issues = initial_issues if prepared == code else static_analysis(prepared)

    state = {"code": prepared, "original_code": code, "history": [],
             "last_issue": None, "last_patch": None, "issues": prepared_issues,
             "initial_issues": initial_issues, "auto_fixed": prepared != code}

    # Nothing left for the model to do: skip it entirely (saves ~10 minutes per file).
    if not prepared_issues:
        state["history"].append({"thought": "No issues remain after automatic formatting.",
                                 "action": "finish", "action_input": {}, "observation": "done"})
        return state

    seen_actions = set()
    nudges = 0

    for i in range(max_iter):
        prompt = build_prompt(state)
        raw = call_slm(prompt, model="qwen-refactor-7b")
        full_output = "Thought: " + raw  # re-attach what the prompt consumed
        parsed = parse_react_output(full_output)

        if parsed["action"] is None:
            state["history"].append({"thought": "PARSE_FAILURE", "action": None,
                                       "action_input": {}, "observation": raw[:200]})
            break

        if parsed["action"] == "finish":
            # Finish guard: do not trust the model's claim that it is done.
            # Re-run static analysis on the current code; if issues remain and
            # there is budget left, refuse and say exactly what is left.
            remaining = static_analysis(state["code"])
            if remaining and nudges < MAX_FINISH_NUDGES and i < max_iter - 1:
                nudges += 1
                state["issues"] = remaining
                symbols = [r.get("symbol") for r in remaining]
                state["history"].append({**parsed, "observation":
                    f"NOT FINISHED: static analysis still reports {len(remaining)} issue(s): "
                    f"{symbols}. Fix them (propose_patch, then apply_and_test) before finishing."})
                continue
            state["history"].append({**parsed, "observation": "done"})
            break

        # include the current code: after an accepted patch the state has changed, so the
        # same-looking action (e.g. apply_and_test with {}) is no longer a repeat
        action_key = (parsed["action"], str(parsed["action_input"]), state["code"])
        if action_key in seen_actions:
            state["history"].append({**parsed, "observation": "SKIPPED: repeated action"})
            break
        seen_actions.add(action_key)

        state["last_thought"] = parsed["thought"] or ""
        observation = execute_tool(parsed["action"], parsed["action_input"], state, call_slm)
        state["history"].append({**parsed, "observation": observation})

    return state


def run_agent_on_repo(files: list[dict], call_slm) -> list[dict]:
    results = []
    for f in files:
        print(f"Processing {f['filepath']}...")
        result = run_agent(f["code"], call_slm)
        results.append({"filepath": f["filepath"], "source": f["source"], **result})
    return results


def extract_summary(state: dict) -> dict:
    """Pull out issues found and the final accepted patch from a completed run."""
    issues_found = list(state.get("initial_issues") or [])
    final_patch = None
    candidate_patch = None
    original_code = state.get("original_code", state["code"])

    for h in state["history"]:
        # keep the FIRST analysis: later ones only list what is left after fixes
        if h["action"] == "static_analysis" and h.get("observation") and not issues_found:
            try:
                issues_found = eval(h["observation"])
            except Exception:
                pass
        if h["action"] == "propose_patch" and h.get("observation"):
            candidate_patch = h["observation"]
        if h["action"] == "apply_and_test" and h.get("observation"):
            try:
                verify_result = eval(h["observation"])
                if verify_result.get("status") == "ACCEPTED":
                    final_patch = candidate_patch
            except Exception:
                pass

    # The result is the verified, cumulative code (accepted patches + automatic formatting)
    if final_patch is not None or state.get("auto_fixed"):
        final_patch = state["code"]

    return {
        "original_code": original_code,
        "issues_found": issues_found,
        "final_patch": final_patch
    }