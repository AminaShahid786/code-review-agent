import ast
import re
import json

def extract_balanced_json(text: str) -> str | None:
    """Find the first {...} block with properly matched braces, handling nesting."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i+1]
    return None

def parse_literal(text: str):
    """Parse JSON, or failing that a Python dict literal. The model often writes
    {'issue': ...} with single quotes, which json.loads rejects. Returns None if
    neither works. ast.literal_eval only reads literals, it never runs code."""
    try:
        return json.loads(text, strict=False)
    except (json.JSONDecodeError, ValueError):
        pass
    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
        return None

def unwrap_raw(value, max_depth: int = 10):
    """Undo the model re-stringifying its own input: {"_raw": "{'_raw': \"{...}\"}"}
    (nested any number of times) or a dict written as a string -> the real dict."""
    for _ in range(max_depth):
        if isinstance(value, dict) and set(value) == {"_raw"} and isinstance(value["_raw"], str):
            inner = parse_literal(value["_raw"])
        elif isinstance(value, str) and value.lstrip().startswith("{"):
            inner = parse_literal(value)
        else:
            break
        if inner is None:
            break
        value = inner
    return value

def parse_react_output(text: str) -> dict:
    thought_match = re.search(r"Thought:\s*(.*?)(?=Action:|$)", text, re.DOTALL)
    action_match = re.search(r"Action:\s*(\w+)", text)

    thought = thought_match.group(1).strip() if thought_match else None
    if thought:
        # the model sometimes repeats the "Thought:" label the prompt already ends with
        thought = re.sub(r"^(Thought:\s*)+", "", thought)
    action = action_match.group(1).strip() if action_match else None

    action_input = {}
    input_section = text[text.find("Action Input:"):] if "Action Input:" in text else ""
    raw_json = extract_balanced_json(input_section)
    if raw_json:
        parsed = unwrap_raw(parse_literal(raw_json))
        action_input = parsed if isinstance(parsed, dict) else {"_raw": raw_json}

    return {"thought": thought, "action": action, "action_input": action_input}
