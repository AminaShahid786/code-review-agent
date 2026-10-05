import subprocess
import json
import ast

def static_analysis(code: str, filepath: str = "temp.py") -> list[dict]:
    """Run pylint on code, return structured issues."""
    with open(filepath, "w") as f:
        f.write(code)

    result = subprocess.run(
        ["pylint", filepath, "--output-format=json"],
        capture_output=True, text=True
    )
    try:
        issues = json.loads(result.stdout) if result.stdout else []
    except json.JSONDecodeError:
        issues = []

    return [
        {
            "line": i["line"],
            "type": i["type"],
            "message": i["message"],
            "symbol": i["symbol"]
        }
        for i in issues
    ]

def is_syntax_valid(code: str) -> bool:
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False