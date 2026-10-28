from app.ai import Mode
from app.stages import implementer, planner, tester
from app.stages.planner import CommandResult


class CopilotProvider:
    """The Copilot CLI, run exactly as the stages always have."""

    id = "copilot"
    label = "GitHub Copilot CLI"

    def __init__(self, command: str, runner=planner.run_command):
        self.command = command
        self.runner = runner

    async def run(
        self, prompt: str, cwd: str, timeout: float, mode: Mode = "plan"
    ) -> CommandResult:
        build = {
            "plan": planner.build_args,
            "test": tester.build_args,
            "summary": implementer.summary_args,
        }[mode]
        return await self.runner(build(self.command, prompt), cwd, timeout)
