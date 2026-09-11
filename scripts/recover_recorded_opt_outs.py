"""Operator-only entry point for recorded opt-out recovery."""

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NoReturn, TextIO

from app.application.use_cases.recover_recorded_opt_outs import (
    LeadOptOutRecoveryResult,
    OptOutRecoveryReport,
    OptOutRecoveryRepository,
    RecoverOptOutsRequest,
    RecoveryStatus,
    recover_recorded_opt_outs,
)


class _RecoveryArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        # argparse errors can echo arbitrary input, including pasted credentials.
        raise ValueError("Invalid recovery arguments.")


def _parse_request(argv: Sequence[str] | None) -> tuple[RecoverOptOutsRequest, Path]:
    parser = _RecoveryArgumentParser(
        prog="python -m scripts.recover_recorded_opt_outs",
        description=__doc__,
        allow_abbrev=False,
        argument_default=argparse.SUPPRESS,
    )
    parser.add_argument("--workspace-id", required=True, help="Workspace UUID to recover.")
    parser.add_argument(
        "--lead-id", dest="lead_ids", action="append", required=True,
        help="Explicit lead UUID; repeat for a bounded scope of up to 100 leads.",
    )
    parser.add_argument(
        "--hold-lead-id", dest="consent_review_hold_ids", action="append",
        help="Scoped lead UUID requiring consent review; repeat as needed. Never repaired.",
    )
    parser.add_argument(
        "--max-events-per-lead", type=int,
        help="Retained-event ceiling per lead (default 1000; maximum 10000).",
    )
    parser.add_argument("--apply", action="store_true", help="Apply repairs; otherwise dry-run.")
    parser.add_argument(
        "--reviewed-for-lifts", action="store_true",
        help="Acknowledge review of the non-held scope for unrecorded legitimate lifts.",
    )
    parser.add_argument(
        "--report", type=Path, required=True,
        help="New private JSONL report path. Existing files are never overwritten.",
    )
    arguments = vars(parser.parse_args(argv))
    report_path = Path(arguments.pop("report"))
    return RecoverOptOutsRequest.model_validate(arguments), report_path


def _open_report(path: Path) -> TextIO:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        return open(descriptor, "w", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise


def _write_record(report_file: TextIO, record: Mapping[str, object]) -> None:
    report_file.write(json.dumps(record) + "\n")
    report_file.flush()
    os.fsync(report_file.fileno())


async def _recover_leads(
    request: RecoverOptOutsRequest,
    repository: OptOutRecoveryRepository,
    report_file: TextIO,
) -> OptOutRecoveryReport:
    results: list[LeadOptOutRecoveryResult] = []
    for lead_id in request.lead_ids:
        # Revalidate the subset rather than bypassing scope checks with model_copy.
        lead_request = RecoverOptOutsRequest(
            workspace_id=request.workspace_id,
            lead_ids=(lead_id,),
            apply=request.apply,
            reviewed_for_lifts=request.reviewed_for_lifts,
            consent_review_hold_ids=(
                (lead_id,) if lead_id in request.consent_review_hold_ids else ()
            ),
            max_events_per_lead=request.max_events_per_lead,
        )
        lead_report = await recover_recorded_opt_outs(request=lead_request, repository=repository)
        result = lead_report.leads[0]
        # The repository owns the transaction and returns only after any commit.
        _write_record(report_file, {
            "type": "lead",
            "lead_id": str(result.lead_id),
            "status": result.status.value,
            "candidate": result.candidate,
            "reasons": list(result.reasons),
            "references": list(result.references),
        })
        results.append(result)
    return OptOutRecoveryReport(leads=tuple(results))


async def _run_recovery(
    request: RecoverOptOutsRequest,
    repository: OptOutRecoveryRepository | None,
    report_file: TextIO,
) -> OptOutRecoveryReport:
    if repository is not None:
        return await _recover_leads(request, repository, report_file)

    # Importing database configuration is itself runtime work: the scoped header
    # must already be durable, even if settings or adapter initialization fails.
    from app.core.database import async_engine, async_session_factory

    try:
        from app.infrastructure.persistence.postgres.opt_out_recovery import (
            PostgresOptOutRecoveryRepository,
        )

        return await _recover_leads(
            request, PostgresOptOutRecoveryRepository(async_session_factory), report_file,
        )
    finally:
        await async_engine.dispose()


def _write_completion(
    report_file: TextIO, request: RecoverOptOutsRequest, result: OptOutRecoveryReport,
) -> None:
    completion_offset = report_file.tell()
    try:
        _write_record(report_file, {
            "type": "completed",
            "totals": {
                "scoped": len(request.lead_ids),
                "processed": len(result.leads),
                "candidate": result.candidate,
                "clean": sum(lead.status == RecoveryStatus.CLEAN for lead in result.leads),
                "already_correct": result.already_correct,
                "would_change": result.would_change,
                "changed": result.changed,
                "unresolved": result.unresolved,
                "failed": result.failed,
            },
        })
    except BaseException:
        # A failed final append/fsync must not leave a misleading completion marker.
        report_file.seek(completion_offset)
        report_file.truncate()
        report_file.flush()
        os.fsync(report_file.fileno())
        raise


def main(
    argv: Sequence[str] | None = None,
    *,
    repository: OptOutRecoveryRepository | None = None,
) -> int:
    try:
        try:
            request, report_path = _parse_request(argv)
        except ValueError:
            print(
                "Recovery arguments are invalid; use --help for the required scope.",
                file=sys.stderr,
            )
            return 2
        except SystemExit as exc:
            # argparse's --help remains usable without opening a report or database.
            return 0 if exc.code == 0 else 2

        with _open_report(report_path) as report_file:
            _write_record(report_file, {
                "type": "header",
                "workspace_id": str(request.workspace_id),
                "lead_ids": [str(lead_id) for lead_id in request.lead_ids],
                "consent_review_hold_ids": [
                    str(lead_id) for lead_id in request.consent_review_hold_ids
                ],
                "mode": "apply" if request.apply else "dry_run",
                "reviewed_for_lifts": request.reviewed_for_lifts,
                "max_events_per_lead": request.max_events_per_lead,
            })
            result = asyncio.run(_run_recovery(request, repository, report_file))
            # Completing enumeration is distinct from resolving every lead. Any
            # unresolved/failed results still produce a nonzero exit below.
            _write_completion(report_file, request, result)
        return int(bool(result.unresolved or result.failed))
    except (KeyboardInterrupt, asyncio.CancelledError):
        print("Recovery interrupted; any partial report is incomplete.", file=sys.stderr)
        return 130
    except OSError:
        print("Recovery storage failed; do not rely on an incomplete report.", file=sys.stderr)
    except (Exception, SystemExit):
        print("Recovery failed; any partial report is incomplete.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())