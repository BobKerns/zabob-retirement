"""#687: the portable pieces native Windows needs, checked where the tests run."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from zabob.retirement import oscompat
from zabob.retirement.sim import flock


def _open(path: Path) -> int:
    return os.open(path, os.O_RDWR | os.O_CREAT | flock.O_BINARY, 0o644)


def test_locks_behave_like_flock(tmp_path: Path) -> None:
    """Shared locks share, an exclusive one excludes, a try that can't get
    its lock raises BlockingIOError, and closing the file releases it."""
    path = tmp_path / "a.lock"
    first, second = _open(path), _open(path)
    try:
        flock.lock(first, shared=True)
        flock.lock(second, shared=True, block=False)  # both readers
        flock.unlock(second)
        with pytest.raises(BlockingIOError):
            flock.lock(second, block=False)  # a writer waits for the reader
        flock.unlock(first)
        flock.lock(second, block=False)
        with pytest.raises(BlockingIOError):
            flock.lock(first, shared=True, block=False)
    finally:
        os.close(second)
    flock.lock(first, block=False)  # released by the close
    os.close(first)


def test_a_locked_file_can_still_be_read(tmp_path: Path) -> None:
    """lock_holder reads the holder's record while the lock is held; a
    Windows lock covers the bytes it locks, so it locks none of the record."""
    path = tmp_path / "a.lock"
    holder = _open(path)
    try:
        os.write(holder, b'{"pid": 1}')
        flock.lock(holder)
        reader = os.open(path, os.O_RDONLY | flock.O_BINARY)
        try:
            assert os.read(reader, 100) == b'{"pid": 1}'
        finally:
            os.close(reader)
    finally:
        os.close(holder)


def test_login_name_falls_back_when_there_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    assert oscompat.login_name()

    def nobody() -> str:
        raise OSError("no user")
    monkeypatch.setattr(oscompat.getpass, "getuser", nobody)
    assert oscompat.login_name() == "unknown"
    assert oscompat.login_name("analysis") == "analysis"


def test_a_linked_folder_reads_as_the_folder_and_unlinks_alone(tmp_path: Path) -> None:
    target = tmp_path / "runs"
    target.mkdir()
    (target / "a.txt").write_text("a\n", encoding="utf-8")
    link = tmp_path / "linked"
    oscompat.link_dir(link, target)
    assert oscompat.is_link(link) and (link / "a.txt").read_text(encoding="utf-8") == "a\n"
    oscompat.remove_link(link)
    assert not link.exists() and (target / "a.txt").exists()


def test_pid_alive_tells_a_running_process_from_a_finished_one() -> None:
    assert oscompat.pid_alive(os.getpid())
    finished = subprocess.Popen([sys.executable, "-c", "pass"])
    finished.wait()
    assert not oscompat.pid_alive(finished.pid)


def test_kill_tree_stops_a_process_and_its_children(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    script = ("import subprocess, sys, time\n"
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
              f"open({str(marker)!r}, 'w', encoding='utf-8').write(str(child.pid))\n"
              "time.sleep(60)\n")
    proc = oscompat.start_tree([sys.executable, "-c", script])
    child = _child_pid(marker)
    oscompat.kill_tree(proc)
    proc.wait(timeout=10)
    _assert_ends(child)


def test_kill_tree_stops_the_children_of_a_process_that_has_exited(tmp_path: Path) -> None:
    """The case kill_tree runs for at the end of a research run: claude gone,
    a child of its still holding the pipe (taskkill /T can't find those)."""
    marker = tmp_path / "child.pid"
    script = ("import subprocess, sys\n"
              "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
              f"open({str(marker)!r}, 'w', encoding='utf-8').write(str(child.pid))\n")
    proc = oscompat.start_tree([sys.executable, "-c", script])
    child = _child_pid(marker)
    proc.wait(timeout=20)
    assert oscompat.pid_alive(child)
    oscompat.kill_tree(proc)
    _assert_ends(child)


def _child_pid(marker: Path) -> int:
    deadline = time.monotonic() + 20
    while not (marker.exists() and marker.read_text(encoding="utf-8")) and time.monotonic() < deadline:
        time.sleep(0.05)
    return int(marker.read_text(encoding="utf-8"))


def _assert_ends(pid: int) -> None:
    deadline = time.monotonic() + 10
    while oscompat.pid_alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not oscompat.pid_alive(pid)


def test_output_to_a_pipe_is_utf8_on_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect on Windows gets cp1252, which can't write a table's borders."""
    class Stream:
        def __init__(self, encoding: str) -> None:
            self.encoding = encoding

        def reconfigure(self, *, encoding: str) -> None:
            self.encoding = encoding

    out, err = Stream("cp1252"), Stream("UTF-8")
    monkeypatch.setattr(oscompat.sys, "stdout", out)
    monkeypatch.setattr(oscompat.sys, "stderr", err)
    monkeypatch.setattr(oscompat, "WINDOWS", False)
    oscompat.utf8_stdio()
    assert out.encoding == "cp1252"  # elsewhere the locale's is the user's choice
    monkeypatch.setattr(oscompat, "WINDOWS", True)
    oscompat.utf8_stdio()
    assert (out.encoding, err.encoding) == ("utf-8", "UTF-8")
