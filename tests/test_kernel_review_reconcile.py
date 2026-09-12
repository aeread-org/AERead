from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "review_reconcile", ROOT / "tools/ci/reconcile_kernel_review.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
SHA = "a" * 40


class FakeGitHub:
    def __init__(self):
        self.pull = {"number": 7, "state": "open", "draft": False,
                     "head": {"sha": SHA}, "user": {"login": "author"}, "changed_files": 1}
        self.files = [{"filename": "src/aeread/shared_runner/task/receipts.py"}]
        self.reviews = [{"id": 1, "user": {"login": "reviewer"},
                         "state": "APPROVED", "commit_id": SHA}]
        self.runs = [{"id": 10, "head_sha": SHA, "status": "completed",
                      "conclusion": "failure", "run_attempt": 1}]
        self.jobs = [{"name": "kernel-review", "conclusion": "failure"}]
        self.posts = []
        self.dismiss_before_apply = False

    def get(self, path):
        return copy.deepcopy(self.pull)

    def pages(self, path, key=None):
        if "/commits/" in path:
            return [copy.deepcopy(self.pull)]
        if "/files?" in path:
            return self.files
        if "/reviews?" in path:
            return self.reviews
        if key == "workflow_runs":
            if self.dismiss_before_apply:
                self.reviews = []
            return self.runs
        if key == "jobs":
            return self.jobs
        raise AssertionError(path)

    def post(self, path):
        self.posts.append(path)


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out"])
def test_approved_head_reruns_whole_stale_workflow(conclusion):
    api = FakeGitHub()
    api.runs[0]["conclusion"] = conclusion
    api.jobs[0]["conclusion"] = conclusion
    result = MODULE.reconcile(api, "org/repo", SHA, apply=True)
    assert result["rerun_ids"] == [10]
    assert api.posts == ["repos/org/repo/actions/runs/10/rerun"]


def test_dry_run_never_mutates_github():
    api = FakeGitHub()
    result = MODULE.reconcile(api, "org/repo", SHA)
    assert result["candidates"] == [10]
    assert not api.posts


@pytest.mark.parametrize("change", ["author", "old_head", "dismissed", "newer_review",
                                    "draft", "closed", "non_kernel", "truncated_files"])
def test_unapproved_or_inapplicable_pr_cannot_trigger_repairs(change):
    api = FakeGitHub()
    if change == "author":
        api.reviews[0]["user"]["login"] = "author"
    elif change == "old_head":
        api.reviews[0]["commit_id"] = "b" * 40
    elif change == "dismissed":
        api.reviews[0]["state"] = "DISMISSED"
    elif change == "newer_review":
        api.reviews.append(dict(api.reviews[0], id=2, state="CHANGES_REQUESTED"))
    elif change == "draft":
        api.pull["draft"] = True
    elif change == "closed":
        api.pull["state"] = "closed"
    elif change == "non_kernel":
        api.files[0]["filename"] = "docs/example.md"
    elif change == "truncated_files":
        api.pull["changed_files"] = 3001
    assert not MODULE.reconcile(api, "org/repo", SHA, apply=True)["rerun_ids"]
    assert not api.posts


def test_dismissal_during_history_scan_stops_apply():
    api = FakeGitHub()
    api.dismiss_before_apply = True
    result = MODULE.reconcile(api, "org/repo", SHA, apply=True)
    assert result["stopped"] == "approval or head changed before rerun"
    assert not api.posts


def test_comment_does_not_revoke_formal_approval():
    api = FakeGitHub()
    api.reviews.append(dict(api.reviews[0], id=2, state="COMMENTED"))
    assert MODULE.reconcile(api, "org/repo", SHA, apply=True)["rerun_ids"] == [10]


def test_github_pages_are_flattened_before_review_selection(monkeypatch):
    import json

    pages = [[{"id": 1}], [{"id": 101}]]
    calls = []

    def output(command, **kwargs):
        calls.append(command)
        return json.dumps(pages)

    monkeypatch.setattr(MODULE.subprocess, "check_output", output)
    assert MODULE.GitHub().pages("repos/org/repo/pulls/7/reviews") == [{"id": 1}, {"id": 101}]
    assert "--paginate" in calls[0] and "--slurp" in calls[0]


@pytest.mark.parametrize("change", ["other_head", "running", "success", "hygiene_only", "exhausted"])
def test_only_stale_failed_gate_runs_are_retried(change):
    api = FakeGitHub()
    if change == "other_head":
        api.runs[0]["head_sha"] = "b" * 40
    elif change == "running":
        api.runs[0]["status"] = "in_progress"
    elif change == "success":
        api.runs[0]["conclusion"] = "success"
    elif change == "hygiene_only":
        api.jobs = [{"name": "kernel-review", "conclusion": "success"},
                    {"name": "pr-hygiene", "conclusion": "failure"}]
    else:
        api.runs[0]["run_attempt"] = 3
    result = MODULE.reconcile(api, "org/repo", SHA, apply=True)
    assert not api.posts
    assert result["exhausted_ids"] == ([10] if change == "exhausted" else [])


def test_repair_workflow_runs_only_trusted_default_branch_code():
    workflow = (ROOT / ".github/workflows/kernel-review-reconcile.yml").read_text()
    assert "workflows: [pr-lanes]" in workflow
    assert "ref: ${{ github.event.repository.default_branch }}" in workflow
    assert "persist-credentials: false" in workflow
    assert "actions: write" in workflow
    assert "cancel-in-progress: false" in workflow
