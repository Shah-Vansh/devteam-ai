"""One LLM-call budget shared by every stage of a run (MAX_LLM_CALLS_PER_RUN)."""

from app.llm.base import LLMUsage


class LLMBudgetExceeded(Exception):
    """The run would need more LLM calls than MAX_LLM_CALLS_PER_RUN allows."""


class LLMBudget:
    def __init__(self, max_calls: int) -> None:
        self.max_calls = max_calls
        self.usages: list[LLMUsage] = []

    def spend(self, usages: list[LLMUsage]) -> None:
        self.usages.extend(usages)
        if len(self.usages) > self.max_calls:
            raise LLMBudgetExceeded(f"used {len(self.usages)} LLM calls; limit is {self.max_calls}")

    @property
    def calls(self) -> int:
        return len(self.usages)

    @property
    def input_tokens(self) -> int:
        return sum(u.input_tokens for u in self.usages)

    @property
    def output_tokens(self) -> int:
        return sum(u.output_tokens for u in self.usages)
