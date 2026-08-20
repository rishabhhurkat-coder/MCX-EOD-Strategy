"""Start the local MCX UI bridge and Vite frontend on free ports."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BRIDGE = PROJECT_ROOT / "backend" / "ui_bridge.py"
FRONTEND = PROJECT_ROOT / "frontend"
LOG_DIR = PROJECT_ROOT / "data" / "outputs"
LOG_FILE = LOG_DIR / "ui_launcher.log"
HOST = "127.0.0.1"


def free_port(start: int, reserved: set[int]) -> int:
    port = start
    while True:
        if port not in reserved:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                if sock.connect_ex((HOST, port)) != 0:
                    reserved.add(port)
                    return port
        port += 1


def wait_for(url: str, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.5) as response:
                if response.status < 500:
                    return True
        except Exception:
            time.sleep(0.25)
    return False


def start_hidden(command: list[str], cwd: Path, env: dict, log_handle):
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
    )


def main() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    reserved = set()
    bridge_port = free_port(8787, reserved)
    frontend_port = free_port(5173, reserved)
    env = os.environ.copy()
    env["BRIDGE_PORT"] = str(bridge_port)

    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\nStarting bridge={bridge_port}, frontend={frontend_port}\n")
        bridge = start_hidden(
            [sys.executable, str(BRIDGE), "--host", HOST, "--port", str(bridge_port)],
            PROJECT_ROOT,
            env,
            log,
        )
        frontend = start_hidden(
            ["npm.cmd", "run", "dev", "--", "--host", HOST, "--port", str(frontend_port)],
            FRONTEND,
            env,
            log,
        )

    bridge_url = f"http://{HOST}:{bridge_port}/api/health"
    frontend_url = f"http://{HOST}:{frontend_port}/"
    if not wait_for(bridge_url) or not wait_for(frontend_url):
        raise RuntimeError(
            f"MCX UI did not start. Check {LOG_FILE}. "
            f"Bridge PID={bridge.pid}, frontend PID={frontend.pid}."
        )

    state = {
        "bridge_port": bridge_port,
        "frontend_port": frontend_port,
        "bridge_url": bridge_url,
        "frontend_url": frontend_url,
        "bridge_pid": bridge.pid,
        "frontend_pid": frontend.pid,
    }
    (LOG_DIR / "ui_launcher_state.json").write_text(json.dumps(state, indent=2), encoding="utf-8")
    webbrowser.open(frontend_url, new=2)


if __name__ == "__main__":
    main()
