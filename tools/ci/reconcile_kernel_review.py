"""Re-run stale review-gate workflows after a current-head approval.

Dry-run by default. This never writes a success status or merges a PR: the
original workflow must run again and enforce its own review rule.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from typing import Any


KERNEL_PATH = re.compile(
    r"^(src/aeread/shared_runner/|src/aeread/cli\.py$|conftest\.py$|tests/conftest\.py$)"
)
RETRYABLE_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required", "stale"}


class GitHub:
    def get(self, path: str) -> Any:
        return json.loads(subprocess.check_output(["gh", "api", path], text=True))

    def pages(self, path: str, key: str | None = None) -> list[dict]:
        pages = json.loads(subprocess.check_output(
            ["gh", "api", "--paginate", "--slurp", path], text=True
        ))
        return [item for page in pages for item in (page[key] if key else page)]

    def post(self, path: str) -> None:
        subprocess.run(["gh", "api", "--method", "POST", path], check=True)


def approved_head(api: GitHub, repo: str, number: int, sha: str) -> tuple[bool, str]:
    pull = api.get(f"repos/{repo}/pulls/{number}")
    if pull["state"] != "open" or pull["draft"] or pull["head"]["sha"] != sha:
        return False, "PR is closed, draft, or has a newer head"
    files = api.pages(f"repos/{repo}/pulls/{number}/files?per_page=100")
    if len(files) != pull["changed_files"]:
        return False, "incomplete changed-file listing; manual inspection required"
    if not any(KERNEL_PATH.match(item["filename"]) for item in files):
        return False, "not a kernel PR"
    reviews = api.pages(f"repos/{repo}/pulls/{number}/reviews?per_page=100")
    latest: dict[str, dict] = {}
    for review in sorted(reviews, key=lambda item: item["id"]):
        login = review["user"]["login"]
        if (login != pull["user"]["login"]
                and review["state"] in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}):
            latest[login] = review
    # Match pr-lanes.yml: comments do not revoke an existing formal approval.
    approvals = [review for review in latest.values()
                 if review["state"] == "APPROVED" and review["commit_id"] == sha]
    if not approvals:
        return False, "no current-head non-author approval"
    return True, "current-head non-author approval verified"


def reconcile(api: GitHub, repo: str, sha: str, *, apply: bool = False) -> dict:
    pulls = api.pages(f"repos/{repo}/commits/{sha}/pulls?per_page=100")
    eligible = []
    reports = []
    for pull in pulls:
        if pull["state"] != "open" or pull["head"]["sha"] != sha:
            continue
        ok, reason = approved_head(api, repo, pull["number"], sha)
        reports.append({"pr": pull["number"], "eligible": ok, "reason": reason})
        if ok:
            eligible.append(pull["number"])
    result = {"head_sha": sha, "apply": apply, "pull_requests": reports,
              "candidates": [], "rerun_ids": [], "exhausted_ids": []}
    if not eligible:
        return result
    runs = api.pages(
        f"repos/{repo}/actions/workflows/pr-lanes.yml/runs?head_sha={sha}&per_page=100",
        "workflow_runs",
    )
    for run in runs:
        if (run["head_sha"] != sha or run["status"] != "completed"
                or run["conclusion"] not in RETRYABLE_CONCLUSIONS):
            continue
        jobs = api.pages(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100", "jobs")
        if not any(job["name"] == "kernel-review"
                   and job["conclusion"] in RETRYABLE_CONCLUSIONS for job in jobs):
            continue
        if run["run_attempt"] >= 3:
            result["exhausted_ids"].append(run["id"])
            continue
        result["candidates"].append(run["id"])
        if apply:
            # A push or dismissal while reading history must not start a repair
            # justified only by a stale approval snapshot.
            if not any(approved_head(api, repo, number, sha)[0] for number in eligible):
                result["stopped"] = "approval or head changed before rerun"
                break
            # Full workflow, deliberately not /rerun-failed-jobs: partial reruns
            # left cancelled gate instances blocking #176.
            api.post(f"repos/{repo}/actions/runs/{run['id']}/rerun")
            result["rerun_ids"].append(run["id"])
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        parser.error("--repo must be owner/name")
    if not re.fullmatch(r"[0-9a-f]{40}", args.sha):
        parser.error("--sha must be a full commit SHA")
    result = reconcile(GitHub(), args.repo, args.sha, apply=args.apply)
    print(json.dumps(result, indent=2, sort_keys=True))
    if result["exhausted_ids"]:
        raise SystemExit("review-gate rerun limit reached; inspect the reported runs")


if __name__ == "__main__":
    main()
