from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.application.use_cases.recover_recorded_opt_outs import RecoverOptOutsRequest


@pytest.mark.parametrize(
    "override",
    [
        {"lead_ids": ()},
        {"lead_ids": tuple(uuid4() for _ in range(101))},
        {"max_events_per_lead": 0},
        {"max_events_per_lead": 10001},
        {"apply": True},
        {"consent_review_hold_ids": (uuid4(),)},
        {"workspace_id": UUID(int=0)},
        {"lead_ids": (UUID(int=0),)},
        {"unknown_scope_argument": "reject-typos"},
    ],
)
def test_recovery_rejects_unbounded_or_unreviewed_scope(override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RecoverOptOutsRequest.model_validate({
            "workspace_id": uuid4(), "lead_ids": (uuid4(),), **override,
        })


def test_recovery_defaults_to_preview_and_deduplicates_scope() -> None:
    first, second = uuid4(), uuid4()
    request = RecoverOptOutsRequest(
        workspace_id=uuid4(), lead_ids=(first, second, first),
    )
    assert request.apply is False
    assert request.reviewed_for_lifts is False
    assert request.lead_ids == (first, second)
    assert request.max_events_per_lead == 1000