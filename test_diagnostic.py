"""Runs the agent on ONE file with full visibility into every step: the model's
full thought, the exact patch it proposed, and the exact reason each patch was
accepted or rejected. Use this instead of the batch script when something is
failing silently -- it costs one file's worth of time, not five."""
import sys
from adapters.loader import load_local_repo
from agent.loop import run_agent, extract_summary
from agent.llm import call_slm

TARGET_FILENAME = "messy_loops.py"  # change this to try a different file

files = load_local_repo("./sample_repos/test_project")
target = next((f for f in files if f["filepath"].endswith(TARGET_FILENAME)), None)
if not target:
    print(f"Could not find {TARGET_FILENAME}. Available files:")
    for f in files:
        print(" -", f["filepath"])
    sys.exit(1)

print(f"=== Running on {target['filepath']} ===\n")
state = run_agent(target["code"], call_slm, max_iter=8)

print("\n=== FULL STEP-BY-STEP HISTORY ===")
for idx, h in enumerate(state["history"], 1):
    print(f"\n--- Step {idx}: {h['action']} ---")
    print("Thought:", h.get("thought", "")[:300])
    print("Action Input:", h.get("action_input"))
    print("Observation:", h.get("observation"))

summary = extract_summary(state)
print("\n=== SUMMARY ===")
print("Issues found:", len(summary["issues_found"]))
print("Final patch produced:", summary["final_patch"] is not None)
if summary["final_patch"]:
    print("\n--- Final code ---")
    print(summary["final_patch"])