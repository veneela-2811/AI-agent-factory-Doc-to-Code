import pytest
from src.llm.schemas import (
    LLMRequest, LLMMessage, TaskCategory, TaskCapabilityRequirements,
    ReasoningTier, CodingTier, ModelCapability
)
from src.llm.router import AdaptiveLLMRouter, RoutingExhaustedError
from src.llm.base import BaseLLMAdapter


class FailingAdapter(BaseLLMAdapter):
    def __init__(self, config=None):
        pass

    def is_available(self) -> bool:
        return True

    async def health_check(self) -> bool:
        return True

    async def generate(self, request, model):
        raise RuntimeError("Simulated 429 Rate Limit Error")


@pytest.mark.asyncio
async def test_llm_router_cooldown_on_failure():
    router = AdaptiveLLMRouter()
    # Inject failing adapter for all providers to test cooldown hermetically
    for k in list(router.adapters.keys()):
        router.adapters[k] = FailingAdapter()

    req = LLMRequest(
        task_category=TaskCategory.SIMPLE,
        task_name="gap_analysis",
        messages=[LLMMessage(role="user", content="Analyze document gaps")]
    )
    
    try:
        await router.generate(req)
    except Exception:
        pass

    assert len(router.cooldowns) > 0
