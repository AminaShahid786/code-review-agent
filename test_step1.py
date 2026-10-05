from adapters.loader import load_local_repo, load_github_repo

files = load_local_repo("./sample_repos")
print(f"Loaded {len(files)} files")
for f in files[:3]:
    print(f["filepath"])

files = load_github_repo("https://github.com/psf/requests", branch="main")
print(f"Cloned and loaded {len(files)} files")