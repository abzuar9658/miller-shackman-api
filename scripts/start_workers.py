"""Start all background workers and log each to a dedicated file.

Usage:
    arch -arm64 uv run python scripts/start_workers.py [--group all|temporal|workers]

Groups:
    all      - API, Temporal worker, signal dispatcher, outbound send dispatcher,
               outbox publisher,
               CRM sync worker, CRM sync scheduler, CRM webhook retry worker,
               CRM history import worker
    temporal - Temporal worker + signal dispatcher + outbound send dispatcher
    workers  - API + outbound send dispatcher + outbox publisher + CRM sync worker +
               CRM webhook retry worker + CRM history import worker
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "logs"
PID_FILE = LOG_DIR / "workers.pids"


def _worker_command(module_name: str) -> list[str]:
    code = (
        f"import asyncio; from app.interfaces.workers.{module_name} import main; "
        "asyncio.run(main())"
    )
    return [sys.executable, "-c", code]


WORKER_DEFINITIONS: dict[str, list[tuple[str, list[str]]]] = {
    "all": [
        ("api", [sys.executable, "-m", "uvicorn", "app.main:app", "--reload"]),
        ("temporal-worker", _worker_command("temporal_worker")),
        ("temporal-signal-dispatcher", _worker_command("temporal_signal_dispatcher_worker")),
        ("outbound-send-dispatcher", _worker_command("outbound_send_dispatch_worker")),
        ("outbox-publisher", _worker_command("outbox_publisher_worker")),
        ("crm-sync-worker", _worker_command("crm_sync_worker")),
        ("crm-sync-scheduler", _worker_command("crm_sync_scheduler_worker")),
        ("crm-webhook-retry-worker", _worker_command("crm_webhook_retry_worker")),
        ("crm-history-import-worker", _worker_command("crm_history_import_worker")),
    ],
    "temporal": [
        ("temporal-worker", _worker_command("temporal_worker")),
        ("temporal-signal-dispatcher", _worker_command("temporal_signal_dispatcher_worker")),
        ("outbound-send-dispatcher", _worker_command("outbound_send_dispatch_worker")),
    ],
    "workers": [
        ("api", [sys.executable, "-m", "uvicorn", "app.main:app", "--reload"]),
        ("outbound-send-dispatcher", _worker_command("outbound_send_dispatch_worker")),
        ("outbox-publisher", _worker_command("outbox_publisher_worker")),
        ("crm-sync-worker", _worker_command("crm_sync_worker")),
        ("crm-sync-scheduler", _worker_command("crm_sync_scheduler_worker")),
        ("crm-webhook-retry-worker", _worker_command("crm_webhook_retry_worker")),
        ("crm-history-import-worker", _worker_command("crm_history_import_worker")),
    ],
}


def _print(message: str) -> None:
    print(message, flush=True)


PROCESS_PATTERNS: list[tuple[str, str]] = [
    ("api", "uvicorn app.main:app"),
    ("temporal-worker", "temporal_worker import main"),
    ("temporal-signal-dispatcher", "temporal_signal_dispatcher_worker import main"),
    ("outbound-send-dispatcher", "outbound_send_dispatch_worker import main"),
    ("outbox-publisher", "outbox_publisher_worker import main"),
    ("crm-sync-worker", "crm_sync_worker import main"),
    ("crm-sync-scheduler", "crm_sync_scheduler_worker import main"),
    ("crm-webhook-retry-worker", "crm_webhook_retry_worker import main"),
    ("crm-history-import-worker", "crm_history_import_worker import main"),
]


def _find_existing_processes() -> dict[str, list[int]]:
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


def _load_existing_pids() -> dict[str, int]:
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


def _start_process(name: str, command: list[str]) -> subprocess.Popen[Any]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{name}.log"
    log_file = log_path.open("a", buffering=1)
    log_file.write(f"\n--- Started {name} at {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
    log_file.flush()

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    return subprocess.Popen(
        command,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        cwd=PROJECT_ROOT,
        env=env,
        start_new_session=True,
    )


def _write_pid_file(pids: dict[str, int]) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text("\n".join(f"{name}: {pid}" for name, pid in pids.items()) + "\n")


def _bootstrap_rabbitmq_topology() -> None:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from app.core.config import get_settings
    from app.infrastructure.events.rabbitmq.topology import ensure_crm_sync_topology

    settings = get_settings()
    asyncio.run(
        ensure_crm_sync_topology(
            rabbitmq_url=settings.rabbitmq_url,
            exchange_name=settings.crm_sync_exchange_name,
            queue_name=settings.crm_sync_queue_name,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Start backend workers with log files")
    parser.add_argument(
        "--group",
        choices=["all", "temporal", "workers"],
        default="all",
        help="Which set of workers to start",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Start even if some workers from a previous run appear to be running",
    )
    args = parser.parse_args()

    workers = WORKER_DEFINITIONS[args.group]

    existing_pids = _load_existing_pids()
    running_pid_file = {name: pid for name, pid in existing_pids.items() if _is_running(pid)}
    running_detected = _find_existing_processes()
    worker_names = {name for name, _ in workers}
    pid_file_pids = set(running_pid_file.values())
    relevant_detected = {
        name: [pid for pid in pids if pid not in pid_file_pids]
        for name, pids in running_detected.items()
        if name in worker_names and any(pid for pid in pids if pid not in pid_file_pids)
    }

    if (running_pid_file or relevant_detected) and not args.force:
        if running_pid_file:
            _print("Some workers from a previous run are still running:")
            for name, pid in running_pid_file.items():
                _print(f"  {name}: pid {pid}")
        if relevant_detected:
            _print("Some workers are already running on this machine:")
            for name, pids in relevant_detected.items():
                _print(f"  {name}: pids {', '.join(str(p) for p in pids)}")
        _print("\nStop them first with: arch -arm64 make stop-all")
        _print("Or use --force to start new copies anyway.")
        return 1

    _print(f"Starting {args.group} workers...")
    _print(f"Logs will be written to: {LOG_DIR}/")

    if args.group in {"all", "workers"}:
        _print("Bootstrapping RabbitMQ topology...")
        _bootstrap_rabbitmq_topology()

    started_pids: dict[str, int] = {}
    for name, command in workers:
        process = _start_process(name, command)
        started_pids[name] = process.pid
        _print(f"  {name}: pid {process.pid} -> logs/{name}.log")
        time.sleep(0.5)

    _write_pid_file(started_pids)

    _print("\nAll workers started.")
    _print("Tail all logs:")
    _print(f"  tail -f {LOG_DIR}/*.log")
    _print("Or run:")
    _print("  arch -arm64 make tail-logs")
    _print("\nStop all workers:")
    _print("  arch -arm64 make stop-all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
