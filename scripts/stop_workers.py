"""Stop all workers started by scripts/start_workers.py.

Usage:
    arch -arm64 uv run python scripts/stop_workers.py
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PID_FILE = PROJECT_ROOT / "logs" / "workers.pids"

PROCESS_PATTERNS: list[tuple[str, str]] = [
    ("api", "uvicorn app.main:app"),
    ("temporal-worker", "temporal_worker import main"),
    ("temporal-signal-dispatcher", "temporal_signal_dispatcher_worker import main"),
    ("outbox-publisher", "outbox_publisher_worker import main"),
    ("crm-sync-worker", "crm_sync_worker import main"),
    ("crm-sync-scheduler", "crm_sync_scheduler_worker import main"),
    ("crm-history-import-worker", "crm_history_import_worker import main"),
]


def _print(message: str) -> None:
    print(message, flush=True)


def _find_processes() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for name, pattern in PROCESS_PATTERNS:
        try:
            result = subprocess.run(
                ["pgrep", "-f", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            continue
        if result.returncode == 0 and result.stdout.strip():
            lines = result.stdout.strip().splitlines()
            pids = [int(line) for line in lines if line.strip().isdigit()]
            if pids:
                found[name] = pids
    return found


def _load_pids() -> dict[str, int]:
    if not PID_FILE.exists():
        return {}
    pids: dict[str, int] = {}
    for line in PID_FILE.read_text().strip().splitlines():
        if not line.strip():
            continue
        parts = line.split(":", 1)
        if len(parts) == 2 and parts[1].strip().isdigit():
            pids[parts[0].strip()] = int(parts[1].strip())
    return pids


def _is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _stop_process(name: str, pid: int) -> bool:
    if not _is_running(pid):
        _print(f"  {name}: pid {pid} already stopped")
        return True

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        _print(f"  {name}: failed to send SIGTERM to pid {pid}: {exc}")
        return False

    for _ in range(20):
        if not _is_running(pid):
            _print(f"  {name}: pid {pid} stopped")
            return True
        time.sleep(0.25)

    try:
        os.kill(pid, signal.SIGKILL)
        _print(f"  {name}: pid {pid} killed")
        return True
    except OSError as exc:
        _print(f"  {name}: failed to kill pid {pid}: {exc}")
        return False


def main() -> int:
    all_stopped = True
    pids = _load_pids()

    if pids:
        _print("Stopping workers from PID file...")
        for name, pid in pids.items():
            if not _stop_process(name, pid):
                all_stopped = False

    if PID_FILE.exists():
        PID_FILE.unlink()

    detected = _find_processes()
    if detected:
        _print("\nStopping detected worker processes...")
        for name, pid_list in detected.items():
            for pid in pid_list:
                if not _stop_process(name, pid):
                    all_stopped = False

    if not pids and not detected:
        _print("No workers found to stop.")
        return 0

    if all_stopped:
        _print("\nAll workers stopped.")
        return 0
    _print("\nSome workers could not be stopped cleanly.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
