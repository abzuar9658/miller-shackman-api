"""Check if a lead and its CRM conversation events exist in the DB."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check lead and CRM conversation events.")
    parser.add_argument("--lead-id", required=True, type=UUID, help="Lead UUID to inspect.")
    return parser.parse_args()


async def _main() -> int:
    from app.core.config import get_settings
    from app.infrastructure.persistence.postgres.models import (
        CrmConversationEventModel,
        LeadModel,
    )

    args = _parse_args()
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as session:
        lead = await session.execute(
            select(LeadModel).where(LeadModel.lead_id == args.lead_id)
        )
        lead = lead.scalar_one_or_none()

        if lead is None:
            print(f"Lead {args.lead_id} NOT FOUND in the database.")
            return 1

        print(f"Lead found: {lead.lead_id}")
        print(f"  workspace_id: {lead.workspace_id}")
        print(f"  crm_provider: {lead.crm_provider}")
        print(f"  crm_lead_id: {lead.crm_lead_id}")
        print(f"  primary_email: {lead.primary_email}")
        print(f"  primary_phone: {lead.primary_phone}")
        print(f"  last updated: {lead.crm_updated_at}")

        events = await session.execute(
            select(CrmConversationEventModel)
            .where(CrmConversationEventModel.lead_id == args.lead_id)
            .order_by(CrmConversationEventModel.occurred_at.desc())
        )
        events = events.scalars().all()
        print(f"\nCRM conversation events: {len(events)}")
        for event in events:
            content = (event.content or "(no content)")[:100]
            print(
                f"  - {event.activity_type} ({event.direction}) "
                f"at {event.occurred_at}: {content}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
