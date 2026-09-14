import pytest
from src.llm.schemas import (
    LLMRequest, LLMMessage, TaskCategory, TaskCapabilityRequirements,
    ReasoningTier, CodingTier, ModelCapability
)
from src.llm.registry import ModelCapabilityRegistry
from src.llm.router import AdaptiveLLMRouter


@pytest.mark.asyncio
async def test_llm_router_task_classification():
    router = AdaptiveLLMRouter()
    reqs_simple = router.classify_task("doc_classification", TaskCategory.SIMPLE)
    assert reqs_simple.min_reasoning == ReasoningTier.LOW
    assert reqs_simple.min_coding == CodingTier.NONE

    reqs_complex_code = router.classify_task("codegen_worker", TaskCategory.COMPLEX)
    assert reqs_complex_code.min_reasoning == ReasoningTier.HIGH
    assert reqs_complex_code.min_coding == CodingTier.EXPERT


@pytest.mark.asyncio
async def test_llm_router_mock_generation():
    router = AdaptiveLLMRouter()
    request = LLMRequest(
        task_category=TaskCategory.SIMPLE,
        task_name="gap_analysis",
        messages=[LLMMessage(role="user", content="Analyze document gaps")],
        response_schema={"type": "object"}
    )
    response = await router.generate(request)
    assert response.model_used is not None
    assert response.structured_data is not None
    assert response.routing_decision is not None
    assert response.routing_decision.task_name == "gap_analysis"
