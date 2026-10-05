from agent.loop import run_agent
from agent.llm import call_slm

code = """
def calc(a,b,c):
    x=a+b
    y=x*c
    return y
"""

result = run_agent(code, call_slm, 8)
for h in result["history"]:
    print(f"Thought: {h['thought']}")
    print(f"Action: {h['action']}")
    print(f"Observation: {h['observation']}")
    print("---")