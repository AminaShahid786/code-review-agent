from tools.analysis import static_analysis, is_syntax_valid

bad_code = """
def add(a,b):
  x=a+b
  return x
"""

print("--- Static analysis results ---")
issues = static_analysis(bad_code)
for issue in issues:
    print(issue)

print("\n--- Syntax check ---")
print(is_syntax_valid(bad_code))


from agent.llm import call_slm
from tools.patcher import propose_patch

print("\n--- Propose patch for first issue ---")
if issues:
    first_issue = issues[0]
    patched = propose_patch(bad_code, first_issue, call_slm)
    print(patched)