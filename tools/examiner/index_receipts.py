"""Map every sealed receipt on this machine to its attempt directory: {receipt_sha256: [dir, ...]}.

Usage: index_receipts.py <out.json> [root ...]   (default roots: ~/AERead* and ~/AERead-worktrees)
Published copies under evidence/*/receipts are skipped; only run roots count."""
import glob, json, os, sys
from pathlib import Path

out = Path(sys.argv[1])
roots = sys.argv[2:] or sorted(glob.glob(os.path.expanduser("~/AERead*")))


def git_worktrees(checkout: str) -> list[str]:
    """Every worktree git registers for the repo, wherever it lives (temporary session worktrees included)."""
    import subprocess
    try:
        text = subprocess.run(["git", "-C", checkout, "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True).stdout
    except Exception:
        return []
    return [line.split(" ", 1)[1] for line in text.splitlines() if line.startswith("worktree ")]


# any root that is a git checkout contributes all of its registered worktrees too
expanded = []
for r in roots:
    expanded.append(r)
    for w in git_worktrees(r):
        if os.path.isdir(os.path.join(w, "runs")):
            expanded.append(os.path.join(w, "runs"))
roots = sorted(set(os.path.abspath(r) for r in expanded if os.path.isdir(r)))
index: dict[str, list[str]] = {}
files = 0
for root in roots:
    for dirpath, dirnames, filenames in os.walk(root):
        if "/evidence/" in dirpath + "/" and "/receipts" in dirpath:
            dirnames[:] = []
            continue
        if "evaluation_receipt.json" in filenames:
            files += 1
            try:
                sha = json.loads(Path(dirpath, "evaluation_receipt.json").read_bytes()).get("receipt_sha256")
            except Exception:
                continue
            if sha:
                index.setdefault(sha, []).append(dirpath)
out.write_text(json.dumps(index))
print(f"receipt index: {len(index)} digests from {files} receipt files under {len(roots)} roots -> {out}")
