from app.domain.conversations import Handoff
from app.domain.identity import User
from app.domain.leads import CanonicalLeadRecord


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.handoffs: dict[object, Handoff] = {}

    async def list_handoffs(self, workspace_id: object, *, limit: int = 100) -> tuple[Handoff, ...]:
        handoffs = [
            handoff for handoff in self.handoffs.values() if handoff.workspace_id == workspace_id
        ]
        ordered = sorted(
            handoffs,
            key=lambda handoff: (handoff.created_at, handoff.handoff_id),
            reverse=True,
        )
        return tuple(ordered[:limit])

    async def get_by_id(self, workspace_id: object, handoff_id: object) -> Handoff | None:
        handoff = self.handoffs.get(handoff_id)
        if handoff is None or handoff.workspace_id != workspace_id:
            return None
        return handoff

    async def save(self, handoff: Handoff) -> Handoff:
        self.handoffs[handoff.handoff_id] = handoff
        return handoff


class FakeLeadRepository:
    def __init__(self) -> None:
        self.leads: dict[object, CanonicalLeadRecord] = {}

    async def get_by_id(self, workspace_id: object, lead_id: object) -> CanonicalLeadRecord | None:
        lead = self.leads.get(lead_id)
        if lead is None or lead.workspace_id != workspace_id:
            return None
        return lead

    async def get_by_id_for_update(
        self, workspace_id: object, lead_id: object
    ) -> CanonicalLeadRecord | None:
        return await self.get_by_id(workspace_id, lead_id)

    async def get_by_crm_id(
        self, workspace_id: object, crm_provider: object, crm_lead_id: str
    ) -> CanonicalLeadRecord | None:
        for lead in self.leads.values():
            if (
                lead.workspace_id == workspace_id
                and lead.crm_provider == crm_provider
                and lead.crm_lead_id == crm_lead_id
            ):
                return lead
        return None

    async def get_by_primary_phone(
        self,
        workspace_id: object,
        phone_number: str,
    ) -> CanonicalLeadRecord | None:
        normalized = _normalized_phone(phone_number)
        if normalized is None:
            return None
        for lead in self.leads.values():
            if lead.workspace_id != workspace_id or lead.primary_phone is None:
                continue
            if _normalized_phone(lead.primary_phone) == normalized:
                return lead
        return None

    async def get_by_primary_email(
        self,
        workspace_id: object,
        email_address: str,
    ) -> CanonicalLeadRecord | None:
        normalized = _normalized_email(email_address)
        if normalized is None:
            return None
        for lead in self.leads.values():
            if lead.workspace_id != workspace_id or lead.primary_email is None:
                continue
            if _normalized_email(lead.primary_email) == normalized:
                return lead
        return None

    async def upsert(self, record: CanonicalLeadRecord) -> CanonicalLeadRecord:
        self.leads[record.lead_id] = record
        return record


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[object, User] = {}

    async def get_by_id(self, user_id: object) -> User | None:
        return self.users.get(user_id)

    async def get_by_email_normalized(self, email_normalized: str) -> User | None:
        for user in self.users.values():
            if user.email_normalized == email_normalized:
                return user
        return None

    async def save(self, user: User) -> User:
        self.users[user.user_id] = user
        return user


def _normalized_phone(phone_number: str | None) -> str | None:
    if phone_number is None:
        return None
    digits_only = "".join(character for character in phone_number if character.isdigit())
    return digits_only or None


def _normalized_email(email_address: str | None) -> str | None:
    if email_address is None:
        return None
    normalized = email_address.strip().lower()
    return normalized or None
