import os
import requests
from pathlib import Path
from git import Repo
import tempfile

def load_local_repo(path: str) -> list[dict]:
    """Read all .py files from a local directory."""
    files = []
    for filepath in Path(path).rglob("*.py"):
        try:
            code = filepath.read_text(encoding="utf-8")
            files.append({
                "source": "local",
                "filepath": str(filepath),
                "code": code
            })
        except (UnicodeDecodeError, PermissionError):
            continue
    return files

def load_github_repo(repo_url: str, branch: str = "main") -> list[dict]:
    """Clone a GitHub repo to a temp dir and read all .py files."""
    tmp_dir = tempfile.mkdtemp()
    Repo.clone_from(repo_url, tmp_dir, branch=branch, depth=1)
    files = load_local_repo(tmp_dir)
    for f in files:
        f["source"] = "github"
        f["repo_url"] = repo_url
    return files

def load_raw_url(url: str) -> dict:
    """Fetch a single Python file from a raw URL."""
    resp = requests.get(url, timeout=10)
    resp.raise_for_status()
    return {"source": "url", "filepath": url, "code": resp.text}