import asyncio
import json
import os
import stat
from pathlib import Path
from uuid import UUID

import pytest

from app.application.use_cases.recover_recorded_opt_outs import (
    LeadOptOutRecoveryResult,
    OptOutRecoveryRepository,
    RecoverOptOutsRequest,
    RecoveryStatus,
)
from scripts.recover_recorded_opt_outs import main


class FakeOptOutRecoveryRepository(OptOutRecoveryRepository):
    def __init__(self, report_path: Path) -> None:
        self.report_path = report_path
        self.requests: list[RecoverOptOutsRequest] = []
        self.called_lead_ids: list[UUID] = []
        self.changed_ids: list[UUID] = []
        self.reports_before_recovery: list[str] = []
        self.report_modes_before_recovery: list[int] = []
        self.outcomes: dict[UUID, LeadOptOutRecoveryResult | BaseException] = {}

    async def recover_lead(
        self, *, request: RecoverOptOutsRequest, lead_id: UUID
    ) -> LeadOptOutRecoveryResult:
        self.reports_before_recovery.append(
            self.report_path.read_text(encoding="utf-8") if self.report_path.exists() else ""
        )
        self.report_modes_before_recovery.append(stat.S_IMODE(self.report_path.stat().st_mode))
        self.requests.append(request)
        self.called_lead_ids.append(lead_id)
        outcome = self.outcomes.get(lead_id)
        if isinstance(outcome, BaseException):
            raise outcome
        result = outcome if outcome is not None else LeadOptOutRecoveryResult(
            lead_id=lead_id,
            status=RecoveryStatus.CHANGED if request.apply else RecoveryStatus.WOULD_CHANGE,
            candidate=True,
            references=(f"external_events:{UUID(int=3)}",),
        )
        if request.apply and result.status == RecoveryStatus.CHANGED:
            self.changed_ids.append(lead_id)
        return result


def test_dry_run_reports_scoped_candidate_without_writes(tmp_path: Path) -> None:
    workspace_id, lead_id = UUID(int=1), UUID(int=2)
    report_path = tmp_path / "recovery.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)

    exit_code = main(
        [
            "--workspace-id", str(workspace_id),
            "--lead-id", str(lead_id),
            "--report", str(report_path),
        ],
        repository=repository,
    )

    assert exit_code == 0
    assert repository.changed_ids == []
    assert repository.requests == [
        RecoverOptOutsRequest(workspace_id=workspace_id, lead_ids=(lead_id,))
    ]
    header = {
        "type": "header",
        "workspace_id": str(workspace_id),
        "lead_ids": [str(lead_id)],
        "consent_review_hold_ids": [],
        "mode": "dry_run",
        "reviewed_for_lifts": False,
        "max_events_per_lead": 1000,
    }
    assert [json.loads(line) for line in repository.reports_before_recovery] == [header]
    assert [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()] == [
        header,
        {
            "type": "lead",
            "lead_id": str(lead_id),
            "status": "would_change",
            "candidate": True,
            "reasons": [],
            "references": [f"external_events:{UUID(int=3)}"],
        },
        {
            "type": "completed",
            "totals": {
                "scoped": 1,
                "processed": 1,
                "candidate": 1,
                "clean": 0,
                "already_correct": 0,
                "would_change": 1,
                "changed": 0,
                "unresolved": 0,
                "failed": 0,
            },
        },
    ]


_SENSITIVE_DETAIL = "sensitive-diagnostic-sentinel"


def _arguments(report_path: Path, *lead_ids: UUID) -> list[str]:
    arguments = ["--workspace-id", str(UUID(int=1)), "--report", str(report_path)]
    for lead_id in lead_ids:
        arguments.extend(["--lead-id", str(lead_id)])
    return arguments


def _read_report(report_path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in report_path.read_text(encoding="utf-8").splitlines()]


def _assert_safe_error(capsys: pytest.CaptureFixture[str]) -> None:
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("Recovery ")
    assert _SENSITIVE_DETAIL not in captured.err
    assert "Traceback" not in captured.err


def test_apply_reports_each_commit_before_next_scoped_lead(tmp_path: Path) -> None:
    first_id, second_id = UUID(int=2), UUID(int=4)
    report_path = tmp_path / "apply.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)

    exit_code = main(
        _arguments(report_path, first_id, second_id, first_id)
        + ["--apply", "--reviewed-for-lifts", "--max-events-per-lead", "25"],
        repository=repository,
    )

    assert exit_code == 0
    assert repository.called_lead_ids == [first_id, second_id]
    assert repository.changed_ids == [first_id, second_id]
    assert repository.requests == [
        RecoverOptOutsRequest(
            workspace_id=UUID(int=1), lead_ids=(lead_id,), apply=True,
            reviewed_for_lifts=True, max_events_per_lead=25,
        )
        for lead_id in (first_id, second_id)
    ]
    records = _read_report(report_path)
    assert records[0] == {
        "type": "header",
        "workspace_id": str(UUID(int=1)),
        "lead_ids": [str(first_id), str(second_id)],
        "consent_review_hold_ids": [],
        "mode": "apply",
        "reviewed_for_lifts": True,
        "max_events_per_lead": 25,
    }
    assert [row["lead_id"] for row in records[1:-1]] == [str(first_id), str(second_id)]
    assert [row["status"] for row in records[1:-1]] == ["changed", "changed"]
    assert [json.loads(line) for line in repository.reports_before_recovery[0].splitlines()] == (
        records[:1]
    )
    assert [json.loads(line) for line in repository.reports_before_recovery[1].splitlines()] == (
        records[:2]
    )
    assert records[-1] == {
        "type": "completed",
        "totals": {
            "scoped": 2, "processed": 2, "candidate": 2, "clean": 0,
            "already_correct": 0, "would_change": 0, "changed": 2,
            "unresolved": 0, "failed": 0,
        },
    }


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize("all_held", [False, True])
def test_consent_review_holds_never_reach_repository(
    tmp_path: Path, apply: bool, all_held: bool,
) -> None:
    first_id, second_id = UUID(int=2), UUID(int=4)
    held_ids = (first_id, second_id) if all_held else (first_id,)
    report_path = tmp_path / "holds.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)
    arguments = _arguments(report_path, first_id, second_id)
    for held_id in (*held_ids, first_id):
        arguments.extend(["--hold-lead-id", str(held_id)])
    if apply:
        arguments.extend(["--apply", "--reviewed-for-lifts"])

    exit_code = main(arguments, repository=repository)

    assert exit_code != 0
    assert repository.called_lead_ids == ([] if all_held else [second_id])
    assert repository.changed_ids == ([second_id] if apply and not all_held else [])
    assert all(request.consent_review_hold_ids == () for request in repository.requests)
    records = _read_report(report_path)
    assert records[0]["consent_review_hold_ids"] == [str(lead_id) for lead_id in held_ids]
    for held_id in held_ids:
        assert {
            "type": "lead", "lead_id": str(held_id), "status": "unresolved",
            "candidate": False, "reasons": ["operator_consent_review_hold"], "references": [],
        } in records
    assert records[-1]["type"] == "completed"
    totals = records[-1]["totals"]
    assert isinstance(totals, dict)
    assert totals["unresolved"] == len(held_ids)
    assert totals["failed"] == 0


@pytest.mark.parametrize(
    "extra_arguments",
    [
        ["--workspace-id", _SENSITIVE_DETAIL],
        ["--workspace-id", str(UUID(int=0))],
        ["--lead-id", _SENSITIVE_DETAIL],
        ["--lead-id", str(UUID(int=0))],
        ["--hold-lead-id", str(UUID(int=4))],
        ["--hold-lead-id", str(UUID(int=0))],
        ["--max-events-per-lead", "0"],
        ["--max-events-per-lead", "10001"],
        ["--max-events-per-lead", _SENSITIVE_DETAIL],
        ["--apply"],
        ["--unrecognized", _SENSITIVE_DETAIL],
        ["--work", str(UUID(int=1))],
        [
            argument
            for number in range(10, 110)
            for argument in ("--lead-id", str(UUID(int=number)))
        ],
    ],
)
def test_invalid_scope_fails_before_report_or_repository_work(
    tmp_path: Path, extra_arguments: list[str], capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "invalid.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)

    exit_code = main(
        _arguments(report_path, UUID(int=2)) + extra_arguments, repository=repository,
    )

    assert exit_code != 0
    assert repository.requests == []
    assert repository.changed_ids == []
    assert not report_path.exists()
    _assert_safe_error(capsys)


@pytest.mark.parametrize("missing_argument", ["--workspace-id", "--lead-id", "--report"])
def test_required_arguments_cannot_be_omitted(
    tmp_path: Path, missing_argument: str, capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "missing-argument.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)
    arguments = _arguments(report_path, UUID(int=2))
    index = arguments.index(missing_argument)
    del arguments[index:index + 2]

    assert main(arguments, repository=repository) != 0
    assert repository.requests == []
    assert not report_path.exists()
    _assert_safe_error(capsys)


def test_help_requires_no_scope_report_or_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "help.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)

    assert main(["--help"], repository=repository) == 0
    assert repository.requests == []
    assert not report_path.exists()
    captured = capsys.readouterr()
    assert "--workspace-id" in captured.out
    assert "--report" in captured.out
    assert captured.err == ""


def test_report_is_mode_0600_before_recovery(tmp_path: Path) -> None:
    report_path = tmp_path / "private.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)

    assert main(_arguments(report_path, UUID(int=2)), repository=repository) == 0

    assert repository.report_modes_before_recovery == [0o600]
    assert stat.S_IMODE(report_path.stat().st_mode) == 0o600


def test_existing_report_is_never_overwritten(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / f"{_SENSITIVE_DETAIL}.jsonl"
    report_path.write_text("existing report\n", encoding="utf-8")
    original_stat = report_path.stat()
    repository = FakeOptOutRecoveryRepository(report_path)

    exit_code = main(
        _arguments(report_path, UUID(int=2)) + ["--apply", "--reviewed-for-lifts"],
        repository=repository,
    )

    assert exit_code != 0
    assert repository.requests == []
    assert repository.changed_ids == []
    assert report_path.read_text(encoding="utf-8") == "existing report\n"
    assert report_path.stat().st_ino == original_stat.st_ino
    assert report_path.stat().st_mode == original_stat.st_mode
    _assert_safe_error(capsys)


@pytest.mark.parametrize("target_exists", [False, True])
def test_report_symlinks_are_rejected_without_touching_target(
    tmp_path: Path, target_exists: bool, capsys: pytest.CaptureFixture[str],
) -> None:
    target = tmp_path / "target.jsonl"
    if target_exists:
        target.write_text("original target\n", encoding="utf-8")
    report_path = tmp_path / "symlink.jsonl"
    report_path.symlink_to(target)
    repository = FakeOptOutRecoveryRepository(report_path)

    exit_code = main(
        _arguments(report_path, UUID(int=2)) + ["--apply", "--reviewed-for-lifts"],
        repository=repository,
    )

    assert exit_code != 0
    assert repository.requests == []
    assert repository.changed_ids == []
    assert report_path.is_symlink()
    if target_exists:
        assert target.read_text(encoding="utf-8") == "original target\n"
    else:
        assert not target.exists()
    _assert_safe_error(capsys)


@pytest.mark.parametrize("is_directory", [False, True])
def test_unavailable_report_stops_before_recovery(
    tmp_path: Path, is_directory: bool, capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path if is_directory else tmp_path / "missing-parent" / "report.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)

    assert main(_arguments(report_path, UUID(int=2)), repository=repository) != 0

    assert repository.requests == []
    assert repository.changed_ids == []
    _assert_safe_error(capsys)


@pytest.mark.parametrize(
    ("status", "reason", "candidate", "unresolved", "failed"),
    [
        (RecoveryStatus.UNRESOLVED, "missing_evidence", True, 1, 0),
        (RecoveryStatus.FAILED, "recovery_storage_failure", False, 0, 1),
    ],
)
def test_unresolved_and_failed_results_are_counted_without_aborting_other_leads(
    tmp_path: Path, status: RecoveryStatus, reason: str, candidate: bool,
    unresolved: int, failed: int,
) -> None:
    first_id, second_id = UUID(int=2), UUID(int=4)
    report_path = tmp_path / "review.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)
    repository.outcomes[first_id] = LeadOptOutRecoveryResult(
        lead_id=first_id, status=status, candidate=candidate,
        reasons=(reason,), references=(f"external_events:{UUID(int=3)}",),
    )

    exit_code = main(
        _arguments(report_path, first_id, second_id) + ["--apply", "--reviewed-for-lifts"],
        repository=repository,
    )

    assert exit_code != 0
    assert repository.called_lead_ids == [first_id, second_id]
    assert repository.changed_ids == [second_id]
    records = _read_report(report_path)
    assert records[1] == {
        "type": "lead", "lead_id": str(first_id), "status": status.value,
        "candidate": candidate, "reasons": [reason],
        "references": [f"external_events:{UUID(int=3)}"],
    }
    assert records[2]["status"] == "changed"
    assert records[-1] == {
        "type": "completed",
        "totals": {
            "scoped": 2, "processed": 2, "candidate": 2 if candidate else 1, "clean": 0,
            "already_correct": 0, "would_change": 0, "changed": 1,
            "unresolved": unresolved, "failed": failed,
        },
    }


@pytest.mark.parametrize(
    "failure", [RuntimeError, OSError, SystemExit, KeyboardInterrupt, asyncio.CancelledError],
)
def test_runtime_failure_keeps_committed_prefix_and_no_completion_marker(
    tmp_path: Path, failure: type[BaseException], capsys: pytest.CaptureFixture[str],
) -> None:
    first_id, second_id, third_id = UUID(int=2), UUID(int=4), UUID(int=5)
    report_path = tmp_path / "interrupted.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)
    repository.outcomes[second_id] = failure(_SENSITIVE_DETAIL)

    exit_code = main(
        _arguments(report_path, first_id, second_id, third_id)
        + ["--apply", "--reviewed-for-lifts"],
        repository=repository,
    )

    assert exit_code != 0
    assert repository.called_lead_ids == [first_id, second_id]
    assert repository.changed_ids == [first_id]
    records = _read_report(report_path)
    assert [record["type"] for record in records] == ["header", "lead"]
    assert records[0]["lead_ids"] == [str(first_id), str(second_id), str(third_id)]
    assert records[1]["lead_id"] == str(first_id)
    assert records[1]["status"] == "changed"
    assert _SENSITIVE_DETAIL not in report_path.read_text(encoding="utf-8")
    assert [json.loads(line) for line in repository.reports_before_recovery[1].splitlines()] == (
        records
    )
    _assert_safe_error(capsys)


@pytest.mark.parametrize(
    ("failure_at", "processed_ids"),
    [(1, ()), (2, (UUID(int=2),)), (4, (UUID(int=2), UUID(int=4)))],
)
def test_report_fsync_failure_stops_recovery_and_cannot_mark_completion(
    tmp_path: Path, failure_at: int, processed_ids: tuple[UUID, ...],
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = tmp_path / "storage-failure.jsonl"
    repository = FakeOptOutRecoveryRepository(report_path)
    real_fsync = os.fsync
    fsync_calls = 0

    def fail_one_fsync(descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1
        if fsync_calls == failure_at:
            raise OSError(_SENSITIVE_DETAIL)
        real_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_one_fsync)

    exit_code = main(
        _arguments(report_path, UUID(int=2), UUID(int=4)) + ["--apply", "--reviewed-for-lifts"],
        repository=repository,
    )

    assert exit_code != 0
    assert repository.called_lead_ids == list(processed_ids)
    assert repository.changed_ids == list(processed_ids)
    records = _read_report(report_path)
    assert [record["type"] for record in records] == ["header"] + ["lead"] * len(processed_ids)
    assert _SENSITIVE_DETAIL not in report_path.read_text(encoding="utf-8")
    _assert_safe_error(capsys)