from agent.loop import run_agent, extract_summary
from agent.report import generate_report
from agent.llm import call_slm

code = """
def add(a,b):
  x=a+b
  return x
"""

state = run_agent(code, call_slm, max_iter=5)
summary = extract_summary(state)
report = generate_report(summary, call_slm)

print("=== BUGS FOUND ===")
for bug in report["bugs_found"]:
    print(f"- Line {bug.get('line')}: {bug.get('message')}")

print("\n=== CORRECTED CODE ===")
print(report["corrected_code"])

print("\n=== DIFF ===")
print(report["diff"])

print("\n=== EXPLANATION ===")
print(report["explanation"])