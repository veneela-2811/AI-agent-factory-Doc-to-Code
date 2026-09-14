from enum import Enum
from typing import Dict, Any, Optional, List, Type
from pydantic import BaseModel, Field
from datetime import datetime


class TaskCategory(str, Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class ReasoningTier(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    def rank(self) -> int:
        tiers = {"low": 1, "medium": 2, "high": 3}
        return tiers.get(self.value, 1)


class CodingTier(str, Enum):
    NONE = "none"
    BASIC = "basic"
    MEDIUM = "medium"
    EXPERT = "expert"

    def rank(self) -> int:
        tiers = {"none": 0, "basic": 1, "medium": 2, "expert": 3}
        return tiers.get(self.value, 0)


class TaskCapabilityRequirements(BaseModel):
    min_reasoning: ReasoningTier = ReasoningTier.LOW
    min_coding: CodingTier = CodingTier.NONE
    min_context: int = 4000
    requires_structured_output: bool = True
    requires_search: bool = False


class ModelCapability(BaseModel):
    id: str
    name: str
    provider: str
    is_target: bool = False
    is_free: bool = True
    context_window: int = 128000
    reasoning_tier: ReasoningTier = ReasoningTier.MEDIUM
    coding_tier: CodingTier = CodingTier.NONE
    structured_output: bool = True
    supports_search: bool = False
    cost_per_1k_input_tokens: float = 0.0
    cost_per_1k_output_tokens: float = 0.0

    def satisfies(self, reqs: TaskCapabilityRequirements) -> bool:
        if self.reasoning_tier.rank() < reqs.min_reasoning.rank():
            return False
        if self.coding_tier.rank() < reqs.min_coding.rank():
            return False
        if self.context_window < reqs.min_context:
            return False
        if reqs.requires_structured_output and not self.structured_output:
            return False
        if reqs.requires_search and not self.supports_search:
            return False
        return True


class LLMMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str


class LLMRequest(BaseModel):
    task_category: TaskCategory = TaskCategory.SIMPLE
    task_name: str = "generic_task"
    messages: List[LLMMessage]
    response_schema: Optional[Dict[str, Any]] = None  # JSON schema or None
    required_capabilities: Optional[TaskCapabilityRequirements] = None
    temperature: float = 0.2
    max_tokens: Optional[int] = 4000
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    request_id: str
    task_name: str
    task_category: TaskCategory
    required_capabilities: TaskCapabilityRequirements
    selected_provider: str
    selected_model: str
    fallback_count: int = 0
    failure_history: List[Dict[str, Any]] = Field(default_factory=list)
    routing_mode: str = "development"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LLMResponse(BaseModel):
    content: str
    structured_data: Optional[Dict[str, Any]] = None
    model_used: str
    provider_used: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    routing_decision: Optional[RoutingDecision] = None
