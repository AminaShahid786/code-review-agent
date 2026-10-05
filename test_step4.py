from agent.llm import call_slm
from agent.prompts import build_prompt
from agent.parser import parse_react_output

state = {"code": "def add(a,b):\n  return a+b", "history": []}
prompt = build_prompt(state)
raw_output = call_slm(prompt, model="qwen-refactor-7b")
print("--- Raw output ---")
print(raw_output)

full_output = "Thought: " + raw_output  # re-attach what the prompt consumed
print("\n--- Parsed ---")
print(parse_react_output(full_output))