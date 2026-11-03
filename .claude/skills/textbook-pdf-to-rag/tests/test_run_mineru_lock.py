"""run_mineru.py refuses to start while another run writes the same folder."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import run_script
from run_mineru import LOCK_NAME, acquire_lock, write_atomic


def test_second_run_is_refused_while_the_first_is_alive(tmp_path):
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (tmp_path / LOCK_NAME).write_text(f"{sleeper.pid}\n")

        with pytest.raises(RuntimeError, match=str(sleeper.pid)):
            acquire_lock(tmp_path)
    finally:
        sleeper.kill()
        sleeper.wait()


def test_lock_left_by_a_dead_run_is_taken_over(tmp_path):
    finished = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"],
                              capture_output=True, text=True)
    (tmp_path / LOCK_NAME).write_text(finished.stdout)

    lock = acquire_lock(tmp_path)

    assert lock.read_text().strip() == str(os.getpid())


def test_script_exits_with_the_reason_when_locked(tmp_path):
    pdfs, out = tmp_path / "pdf_split", tmp_path / "markdown"
    pdfs.mkdir()
    out.mkdir()
    (pdfs / "Book-1.pdf").write_bytes(b"%PDF-1.4")
    kit = tmp_path / "mineru-kit"
    kit.write_text("#!/bin/sh\nexit 0\n")
    os.chmod(kit, 0o755)
    sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        (out / LOCK_NAME).write_text(f"{sleeper.pid}\n")

        result = run_script("run_mineru.py", "--input", pdfs, "--output", out, "--mineru-kit", kit)
    finally:
        sleeper.kill()
        sleeper.wait()

    assert result.returncode != 0
    assert "正在" in result.stderr and str(sleeper.pid) in result.stderr
    assert (out / LOCK_NAME).exists()  # the other run's lock is not removed


def test_lock_is_released_after_a_run(tmp_path):
    pdfs, out = tmp_path / "pdf_split", tmp_path / "markdown"
    pdfs.mkdir()
    (pdfs / "Book-1.pdf").write_bytes(b"%PDF-1.4")
    kit = tmp_path / "mineru-kit"
    kit.write_text("#!/bin/sh\nexit 3\n")
    os.chmod(kit, 0o755)

    run_script("run_mineru.py", "--input", pdfs, "--output", out, "--mineru-kit", kit)

    assert not (out / LOCK_NAME).exists()


def test_atomic_write_leaves_no_partial_markdown(tmp_path):
    target = tmp_path / "Book-1.md"

    write_atomic(target, "# done\n")

    assert target.read_text() == "# done\n"
    assert [path.name for path in tmp_path.iterdir()] == ["Book-1.md"]
