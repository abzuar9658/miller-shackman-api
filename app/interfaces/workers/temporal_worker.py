from app.infrastructure.workflows.temporal.worker import run_temporal_worker


async def main() -> None:
    await run_temporal_worker()
