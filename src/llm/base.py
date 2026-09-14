from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from src.llm.schemas import LLMRequest, LLMResponse, ModelCapability


class BaseLLMAdapter(ABC):
    @abstractmethod
    def __init__(self, config: Dict[str, Any]):
        pass

    @abstractmethod
    def is_available(self) -> bool:
        pass

    @abstractmethod
    async def generate(self, request: LLMRequest, model: ModelCapability) -> LLMResponse:
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        pass
