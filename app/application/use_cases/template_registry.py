from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.application.ports.repositories import TemplateRepository
from app.application.services.paused_search_drafting_templates import (
    get_paused_search_drafting_template,
    paused_search_template_keys,
)
from app.domain.campaigns.template_registry import (
    TemplateChannel,
    TemplateStatus,
    TemplateVersion,
    validate_template_version,
)


class TemplateBackfillStatus(StrEnum):
    SEEDED = "seeded"
    ALREADY_PRESENT = "already_present"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class TemplateBackfillResult:
    status: TemplateBackfillStatus
    templates: tuple[TemplateVersion, ...] = ()
    unresolved_keys: tuple[str, ...] = ()


async def seed_paused_search_templates(
    *,
    workspace_id: UUID,
    repository: TemplateRepository,
    now: datetime,
) -> TemplateBackfillResult:
    seeded: list[TemplateVersion] = []
    unresolved: list[str] = []
    created_count = 0
    for template_key in paused_search_template_keys():
        source = get_paused_search_drafting_template(template_key)
        if source is None:
            unresolved.append(template_key)
            continue
        existing = await repository.get_by_key_and_version(workspace_id, template_key, 1)
        if existing is not None:
            seeded.append(existing)
            continue
        template = TemplateVersion(
            template_version_id=uuid4(),
            workspace_id=workspace_id,
            template_key=template_key,
            version=1,
            channel=TemplateChannel.EMAIL,
            purpose="paused_search",
            content=source.email_template,
            subject=source.email_subject_template,
            prompt_text=source.email_prompt_text,
            allowed_variables=(
                "agent_name",
                "brokerage_name",
                "lead_first_name",
                "message_body",
            ),
            permitted_use_tags=(
                "no_prohibited_advice",
                "no_financial_advice",
                "no_legal_advice",
                "no_tax_advice",
                "no_investment_advice",
                "no_market_predictions",
                "no_unverified_listing_claims",
            ),
            status=TemplateStatus.APPROVED,
            approved_at=now,
            created_at=now,
        )
        if validate_template_version(template):
            unresolved.append(template_key)
            continue
        seeded.append(await repository.save(template))
        created_count += 1
    if unresolved:
        return TemplateBackfillResult(
            status=TemplateBackfillStatus.UNRESOLVED,
            templates=tuple(seeded),
            unresolved_keys=tuple(unresolved),
        )
    status = (
        TemplateBackfillStatus.SEEDED if created_count else TemplateBackfillStatus.ALREADY_PRESENT
    )
    return TemplateBackfillResult(status=status, templates=tuple(seeded))
