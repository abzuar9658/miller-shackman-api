from datetime import timedelta

from temporalio import activity, workflow


@activity.defn(name="smoke-ping")
async def smoke_ping_activity() -> str:
    return "pong"


@workflow.defn(name="smoke-ping-workflow")
class SmokePingWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(
            smoke_ping_activity,
            start_to_close_timeout=timedelta(seconds=5),
        )
