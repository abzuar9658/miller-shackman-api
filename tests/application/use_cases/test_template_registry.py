from datetime import UTC, datetime
from uuid import UUID

import pytest

from app.application.use_cases.template_registry import (
    TemplateBackfillStatus,
    seed_paused_search_templates,
)
from app.domain.campaigns.template_registry import TemplateVersion


class FakeTemplateRepository:
    def __init__(self) -> None:
        self.templates: dict[tuple[str, int], TemplateVersion] = {}

    async def get_by_id(
        self,
        workspace_id: UUID,
        template_version_id: UUID,
    ) -> TemplateVersion | None:
        return next(
            (
                template
                for template in self.templates.values()
                if template.workspace_id == workspace_id
                and template.template_version_id == template_version_id
            ),
            None,
        )

    async def get_by_key_and_version(
        self,
        workspace_id: UUID,
        template_key: str,
        version: int,
    ) -> TemplateVersion | None:
        return self.templates.get((template_key, version))

    async def get_latest_approved_by_key(
        self,
        workspace_id: UUID,
        template_key: str,
    ) -> TemplateVersion | None:
        matches = [
            template
            for template in self.templates.values()
            if template.workspace_id == workspace_id and template.template_key == template_key
        ]
        return max(matches, key=lambda template: template.version, default=None)

    async def save(self, template: TemplateVersion) -> TemplateVersion:
        self.templates[(template.template_key, template.version)] = template
        return template

    async def list_approved(self, workspace_id: UUID) -> tuple[TemplateVersion, ...]:
        return tuple(self.templates.values())


@pytest.mark.asyncio
async def test_seed_is_idempotent() -> None:
    repository = FakeTemplateRepository()
    workspace_id = UUID("00000000-0000-0000-0000-000000000501")
    now = datetime(2026, 1, 1, tzinfo=UTC)

    first = await seed_paused_search_templates(
        workspace_id=workspace_id,
        repository=repository,
        now=now,
    )
    second = await seed_paused_search_templates(
        workspace_id=workspace_id,
        repository=repository,
        now=now,
    )

    assert first.status is TemplateBackfillStatus.SEEDED
    assert second.status is TemplateBackfillStatus.ALREADY_PRESENT
    assert len(first.templates) == 14
    assert len(repository.templates) == 14

    waiting_for_rates = next(
        template
        for template in first.templates
        if "waiting-for-rates" in template.template_key
    )
    financial_prep = next(
        template
        for template in first.templates
        if "financial-prep" in template.template_key
    )
    waiting_for_inventory = next(
        template
        for template in first.templates
        if "waiting-for-inventory" in template.template_key
    )
    universal_tags = {
        "no_prohibited_advice",
        "no_financial_advice",
        "no_legal_advice",
        "no_tax_advice",
        "no_investment_advice",
        "no_market_predictions",
        "no_unverified_listing_claims",
    }
    assert set(waiting_for_rates.permitted_use_tags) == universal_tags
    assert set(financial_prep.permitted_use_tags) == universal_tags
    assert set(waiting_for_inventory.permitted_use_tags) == universal_tags
