import json

SYSTEM_PROMPT = """You are a Python code review agent. You have access to these tools:

- static_analysis(code): finds issues in code, returns a list of {line, type, message}
- propose_patch(code, issue): generates a fix for one issue, returns new code
- apply_and_test(original_code, patched_code): verifies a patch is safe, returns {status, reason}
- finish(summary): call this when done reviewing, with a summary of what was found/fixed

Respond ONLY in this exact format, one action at a time:

Thought: <your reasoning about what to do next>
Action: <tool name>
Action Input: <JSON with the arguments>

Action Input must be ONE valid JSON object with double quotes, for example:
Action Input: {"issue": {"line": 1, "symbol": "missing-function-docstring"}}

Wait for the Observation before continuing. Do not call the same action with the same input twice."""

def build_prompt(state: dict) -> str:
    history_text = ""
    # Show past inputs as real JSON. Python's dict repr uses single quotes, and the
    # model copies whatever format it sees here, so it stopped writing valid JSON.
    for h in state["history"]:
        history_text += f"\nThought: {h['thought']}\nAction: {h['action']}\nAction Input: {json.dumps(h['action_input'])}\nObservation: {h.get('observation', '')}\n"

    return f"""{SYSTEM_PROMPT}

Code to review:
```python
{state['code']}
```
{history_text}
Thought:"""