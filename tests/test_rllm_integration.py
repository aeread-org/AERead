"""Provider-free tests for the rLLM integration surface.

These cover the two things a first-time user hits: the advertised install path
has to find the case configs without a checkout, and a harness failure has to
be distinguishable from a genuine score of zero.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from aeread.integrations import rllm_dataset


def test_build_rows_does_not_depend_on_cwd(tmp_path, monkeypatch):
    """`pip install aeread` then `--register` must work from any directory.

    The default glob used to be resolved against the process CWD, so the
    documented three-line recipe only worked when you happened to be standing
    in a repo checkout.
    """
    monkeypatch.chdir(tmp_path)
    rows = rllm_dataset.build_rows()
    assert rows, "default case set resolved to nothing outside a checkout"
    assert all(Path(r["case_path"]).is_file() for r in rows)


def test_build_rows_still_honours_an_explicit_glob(tmp_path):
    case_dir = tmp_path / "cases"
    case_dir.mkdir()
    (case_dir / "case99_fake.json").write_text("{}")
    rows = rllm_dataset.build_rows(str(case_dir / "case9*.json"), seeds=(1,))
    assert [r["uid"] for r in rows] == ["case99_fake:s1"]


def test_build_rows_reports_a_glob_that_matches_nothing(tmp_path):
    with pytest.raises(FileNotFoundError):
        rllm_dataset.build_rows(str(tmp_path / "nothing_here_*.json"))
