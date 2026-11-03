"""Shared fixtures: a small MinerU-style work directory built from the eval files."""

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
LECTURES = SKILL / "evals" / "resume-from-mineru-markdown" / "files" / "lecture_md"
sys.path.insert(0, str(SCRIPTS))

FOOTER_PROFILE = {
    "book": "Physics lecture notes",
    "cleanup": {"delete_line_patterns": [r"^Copyright 2024 Example Press"], "replacements": []},
}


def run_script(name: str, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(SCRIPTS / name), *map(str, args)],
                          capture_output=True, text=True)


@pytest.fixture
def work(tmp_path: Path) -> Path:
    """<work>/markdown with three lecture files and a book_profile.json with a footer rule."""
    shutil.copytree(LECTURES, tmp_path / "markdown")
    (tmp_path / "book_profile.json").write_text(json.dumps(FOOTER_PROFILE), encoding="utf-8")
    return tmp_path
