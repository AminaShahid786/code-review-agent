from tools.analysis import static_analysis
from tools.patcher import propose_patch
from sandbox.verify import apply_and_test
from agent.llm import call_slm

bad_code = """
def add(a,b):
  x=a+b
  return x
"""

issues = static_analysis(bad_code)
patched = propose_patch(bad_code, issues[0], call_slm)

print("--- Patched code ---")
print(patched)

print("\n--- Verification result ---")
result = apply_and_test(bad_code, patched)
print(result)