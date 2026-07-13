from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.workflows.temporal.worker import run_temporal_worker


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await run_temporal_worker(settings)
