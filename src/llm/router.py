import time
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from config.settings import settings
from src.llm.schemas import (
    LLMRequest, LLMResponse, TaskCategory, TaskCapabilityRequirements,
    ReasoningTier, CodingTier, ModelCapability, RoutingDecision
)
from src.llm.base import BaseLLMAdapter
from src.llm.registry import ModelCapabilityRegistry
from src.llm.adapters.mock_adapter import MockLLMAdapter
from src.llm.adapters.openai_adapter import OpenAIAdapter
from src.llm.adapters.generic_adapters import (
    GeminiAdapter, GroqAdapter, OpenRouterAdapter, OllamaAdapter
)

logger = logging.getLogger("llm_router")


class RoutingExhaustedError(Exception):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message)
        self.details = details or {}


class AdaptiveLLMRouter:
    def __init__(self, registry: Optional[ModelCapabilityRegistry] = None):
        self.registry = registry or ModelCapabilityRegistry()
        self.adapters: Dict[str, BaseLLMAdapter] = {
            "mock": MockLLMAdapter(),
            "openai": OpenAIAdapter(),
            "gemini": GeminiAdapter(),
            "groq": GroqAdapter(),
            "openrouter": OpenRouterAdapter(),
            "ollama": OllamaAdapter(),
        }
        self.cooldowns: Dict[str, float] = {}  # provider -> cooldown_until_timestamp
        self.telemetry_history: List[RoutingDecision] = []

    def classify_task(self, task_name: str, category: TaskCategory) -> TaskCapabilityRequirements:
        if category == TaskCategory.SIMPLE:
            return TaskCapabilityRequirements(
                min_reasoning=ReasoningTier.LOW,
                min_coding=CodingTier.NONE,
                min_context=4000,
                requires_structured_output=True,
                requires_search=False
            )
        elif category == TaskCategory.MEDIUM:
            return TaskCapabilityRequirements(
                min_reasoning=ReasoningTier.MEDIUM,
                min_coding=CodingTier.NONE,
                min_context=8000,
                requires_structured_output=True,
                requires_search=False
            )
        else:  # COMPLEX
            requires_coding = "code" in task_name.lower() or "develop" in task_name.lower()
            return TaskCapabilityRequirements(
                min_reasoning=ReasoningTier.HIGH,
                min_coding=CodingTier.EXPERT if requires_coding else CodingTier.NONE,
                min_context=16000,
                requires_structured_output=True,
                requires_search="research" in task_name.lower()
            )

    def _is_provider_healthy(self, provider_name: str) -> bool:
        cooldown_until = self.cooldowns.get(provider_name, 0.0)
        return time.time() >= cooldown_until

    def _set_provider_cooldown(self, provider_name: str, duration_sec: int = None) -> None:
        duration = duration_sec or settings.PROVIDER_COOLDOWN_SECONDS
        self.cooldowns[provider_name] = time.time() + duration
        logger.warning(f"Provider {provider_name} placed on cooldown for {duration}s")

    async def generate(self, request: LLMRequest) -> LLMResponse:
        req_id = str(uuid.uuid4())
        requirements = request.required_capabilities or self.classify_task(
            request.task_name, request.task_category
        )

        candidates = self.registry.get_capable_models(
            requirements, mode=settings.LLM_ROUTING_MODE
        )

        if not candidates:
            # If no model matches strict search/context, fallback to standard mock or any capable model
            requirements.requires_search = False
            candidates = self.registry.get_capable_models(requirements, mode=settings.LLM_ROUTING_MODE)

        if not candidates:
            raise RoutingExhaustedError(
                f"No capable models found satisfying requirements for task: {request.task_name}",
                details={"requirements": requirements.model_dump(), "mode": settings.LLM_ROUTING_MODE}
            )

        failures = []
        fallback_count = 0

        for candidate in candidates:
            provider_name = candidate.provider
            adapter = self.adapters.get(provider_name)
            
            if not adapter or not adapter.is_available():
                failures.append({"model": candidate.id, "provider": provider_name, "reason": "Adapter not configured or unavailable"})
                continue

            if not self._is_provider_healthy(provider_name):
                failures.append({"model": candidate.id, "provider": provider_name, "reason": "Provider in active rate-limit/failure cooldown"})
                continue

            try:
                logger.info(f"Executing task '{request.task_name}' on model {candidate.id} ({provider_name})")
                response = await adapter.generate(request, candidate)
                
                decision = RoutingDecision(
                    request_id=req_id,
                    task_name=request.task_name,
                    task_category=request.task_category,
                    required_capabilities=requirements,
                    selected_provider=provider_name,
                    selected_model=candidate.id,
                    fallback_count=fallback_count,
                    failure_history=failures,
                    routing_mode=settings.LLM_ROUTING_MODE,
                    timestamp=datetime.now(timezone.utc)
                )
                response.routing_decision = decision
                self.telemetry_history.append(decision)
                return response

            except Exception as e:
                logger.error(f"Execution failed on {candidate.id} ({provider_name}): {str(e)}")
                self._set_provider_cooldown(provider_name)
                failures.append({"model": candidate.id, "provider": provider_name, "reason": str(e)})
                fallback_count += 1

        # If all candidates failed, try deterministic mock as final safety net in development mode
        if settings.LLM_ROUTING_MODE == "development" and "mock" in self.adapters:
            mock_model = self.registry.get_model("mock-target-model") or ModelCapability(
                id="mock-fallback", name="Mock Fallback", provider="mock",
                reasoning_tier=ReasoningTier.HIGH, coding_tier=CodingTier.EXPERT
            )
            mock_response = await self.adapters["mock"].generate(request, mock_model)
            mock_decision = RoutingDecision(
                request_id=req_id,
                task_name=request.task_name,
                task_category=request.task_category,
                required_capabilities=requirements,
                selected_provider="mock",
                selected_model=mock_model.id,
                fallback_count=fallback_count,
                failure_history=failures,
                routing_mode=settings.LLM_ROUTING_MODE,
                timestamp=datetime.now(timezone.utc)
            )
            mock_response.routing_decision = mock_decision
            self.telemetry_history.append(mock_decision)
            return mock_response

        raise RoutingExhaustedError(
            f"All capable models failed for task: {request.task_name}",
            details={"failures": failures, "requirements": requirements.model_dump()}
        )


router = AdaptiveLLMRouter()
