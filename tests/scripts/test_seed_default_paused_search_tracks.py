"""Tests for paused-search default track seeding script argument parsing."""

from scripts.seed_default_paused_search_tracks import parse_args


def test_parse_args_defaults() -> None:
    args = parse_args(
        [
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--actor-user-id",
            "00000000-0000-0000-0000-000000000002",
        ]
    )

    assert str(args.workspace_id) == "00000000-0000-0000-0000-000000000001"
    assert str(args.actor_user_id) == "00000000-0000-0000-0000-000000000002"
    assert args.dry_run is False
    assert args.format == "table"


def test_parse_args_supports_dry_run_and_json_output() -> None:
    args = parse_args(
        [
            "--workspace-id",
            "00000000-0000-0000-0000-000000000001",
            "--actor-user-id",
            "00000000-0000-0000-0000-000000000002",
            "--dry-run",
            "--format",
            "json",
        ]
    )

    assert args.dry_run is True
    assert args.format == "json"
