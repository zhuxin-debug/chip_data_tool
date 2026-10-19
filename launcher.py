"""Local launcher: reuse this project's running instance or select a free port."""
from __future__ import annotations

import json
import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = PROJECT_DIR / ".local"


def free_port() -> int:
    for port in range(8501, 8521):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Ports 8501-8520 are busy. Close an unused local app and retry.")


def healthy(port: int) -> bool:
    try:
        # Local health requests must not be sent through a system HTTP proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
            return response.status == 200 and response.read(16).strip() == b"ok"
    except OSError:
        return False


def main(open_browser: bool = True) -> int:
    RUNTIME_DIR.mkdir(exist_ok=True)
    # The launcher keeps the lock for the server lifetime. Metadata alone never
    # authorizes reusing a possibly unrelated service on an old port.
    lock_path = RUNTIME_DIR / "server.lock"
    with lock_path.open("a+b") as lock:
        lock.seek(0)
        if os.fstat(lock.fileno()).st_size == 0:
            lock.write(b"0")
            lock.flush()
        lock.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            try:
                metadata = json.loads((RUNTIME_DIR / "server.json").read_text(encoding="utf-8"))
                port = metadata["port"]
                if type(port) is int and 8501 <= port <= 8520 and healthy(port):
                    if open_browser:
                        webbrowser.open(f"http://127.0.0.1:{port}")
                    print(f"Already running: http://127.0.0.1:{port}")
                    return 0
            except (OSError, ValueError, KeyError):
                pass
            print("This project is starting. Retry in a few seconds.")
            return 1
        port = free_port()
        url = f"http://127.0.0.1:{port}"
        (RUNTIME_DIR / "server.json").write_text(json.dumps({"port": port}), encoding="utf-8")
        args = [sys.executable, "-m", "streamlit", "run", str(PROJECT_DIR / "app.py"),
                "--server.address", "127.0.0.1", "--server.port", str(port),
                "--server.headless", "true", "--browser.gatherUsageStats", "false"]
        process = subprocess.Popen(args, cwd=PROJECT_DIR,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        try:
            for _ in range(100):
                if process.poll() is not None:
                    print("App failed to start. Run setup.bat to check dependencies.")
                    return process.returncode or 1
                if healthy(port):
                    if open_browser:
                        webbrowser.open(url)
                    print(f"Chip Data Tool: {url}\nKeep this window open. Press Ctrl+C to stop.")
                    break
                time.sleep(0.2)
            else:
                print(f"Startup timed out. Open {url} manually or check local permissions.")
            return process.wait()
        except KeyboardInterrupt:
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start Chip Data Tool locally")
    parser.add_argument("--no-browser", action="store_true", help="Start or reuse the server without opening a browser")
    options = parser.parse_args()
    try:
        raise SystemExit(main(open_browser=not options.no_browser))
    except (OSError, RuntimeError) as exc:
        print(f"Cannot start Chip Data Tool: {exc}")
        raise SystemExit(1)
