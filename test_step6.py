from adapters.loader import load_local_repo
from agent.loop import run_agent_on_repo
from agent.llm import call_slm
import json
from datetime import datetime

files = load_local_repo("./sample_repos/test_project")
results = run_agent_on_repo(files, call_slm)

fname = f"logs/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
with open(fname, "w") as f:
    json.dump(results, f, indent=2, default=str)

print(f"\nSaved {len(results)} results to {fname}")