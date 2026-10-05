from adapters.loader import load_local_repo
from agent.loop import run_agent, extract_summary
from agent.report import generate_report
from agent.llm import call_slm
import json
from datetime import datetime

def run_batch_report(folder_path: str):
    files = load_local_repo(folder_path)
    all_reports = []

    for f in files:
        print(f"\n{'='*60}")
        print(f"Processing: {f['filepath']}")
        print('='*60)

        state = run_agent(f["code"], call_slm, 8)
        summary = extract_summary(state)
        report = generate_report(summary, call_slm)

        print("\n--- BUGS FOUND ---")
        if report["bugs_found"]:
            for bug in report["bugs_found"]:
                print(f"- Line {bug.get('line')}: {bug.get('message')}")
        else:
            print("(none)")

        print("\n--- CORRECTED CODE ---")
        print(report["corrected_code"] or "(no verified fix produced)")

        print("\n--- DIFF ---")
        print(report["diff"] or "(no diff)")

        print("\n--- EXPLANATION ---")
        print(report["explanation"])

        all_reports.append({
            "filepath": f["filepath"],
            **report
        })

    fname = f"logs/report_batch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(fname, "w") as out:
        json.dump(all_reports, out, indent=2, default=str)

    print(f"\n\n{'='*60}")
    print(f"Saved {len(all_reports)} reports to {fname}")
    print('='*60)

if __name__ == "__main__":
    run_batch_report("./sample_repos/test_project")