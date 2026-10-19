import json
import sys

import launcher


def test_second_launch_reuses_locked_running_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(launcher, "RUNTIME_DIR", tmp_path)
    monkeypatch.setattr(launcher, "healthy", lambda port: port == 8501)
    (tmp_path / "server.json").write_text(json.dumps({"port": 8501}), encoding="utf-8")
    calls = []
    monkeypatch.setattr(launcher.webbrowser, "open", calls.append)
    with (tmp_path / "server.lock").open("w+b") as lock:
        lock.write(b"0")
        lock.flush()
        lock.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert launcher.main(open_browser=False) == 0
        assert calls == []
        assert launcher.main() == 0
        assert calls == ["http://127.0.0.1:8501"]
