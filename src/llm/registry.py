import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional
from config.settings import settings
from src.llm.schemas import ModelCapability, TaskCapabilityRequirements, ReasoningTier, CodingTier


class ModelCapabilityRegistry:
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or settings.PROVIDERS_CONFIG_PATH
        self.providers: Dict[str, Dict] = {}
        self.models: Dict[str, ModelCapability] = {}
        self._load_config()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            return
        
        with open(self.config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}

        providers_data = data.get("providers", {})
        for p_name, p_info in providers_data.items():
            self.providers[p_name] = p_info
            for m in p_info.get("models", []):
                cap = ModelCapability(
                    id=m["id"],
                    name=m["name"],
                    provider=p_name,
                    is_target=m.get("is_target", False),
                    is_free=m.get("is_free", True),
                    context_window=m.get("context_window", 128000),
                    reasoning_tier=ReasoningTier(m.get("reasoning_tier", "medium")),
                    coding_tier=CodingTier(m.get("coding_tier", "none")),
                    structured_output=m.get("structured_output", True),
                    supports_search=m.get("supports_search", False),
                    cost_per_1k_input_tokens=m.get("cost_per_1k_input_tokens", 0.0),
                    cost_per_1k_output_tokens=m.get("cost_per_1k_output_tokens", 0.0)
                )
                self.models[cap.id] = cap

    def get_model(self, model_id: str) -> Optional[ModelCapability]:
        return self.models.get(model_id)

    def get_capable_models(
        self,
        requirements: TaskCapabilityRequirements,
        mode: str = "development"
    ) -> List[ModelCapability]:
        capable = [m for m in self.models.values() if m.satisfies(requirements)]

        def _is_configured(provider: str) -> bool:
            if provider == "gemini":
                return bool(os.getenv("GEMINI_API_KEY") or settings.GEMINI_API_KEY)
            elif provider == "openai":
                return bool(os.getenv("OPENAI_API_KEY") or settings.OPENAI_API_KEY)
            elif provider == "groq":
                return bool(os.getenv("GROQ_API_KEY") or settings.GROQ_API_KEY)
            elif provider == "openrouter":
                return bool(os.getenv("OPENROUTER_API_KEY") or settings.OPENROUTER_API_KEY)
            elif provider == "ollama":
                return bool(os.getenv("OLLAMA_BASE_URL") or settings.OLLAMA_BASE_URL)
            return False

        if mode == "development":
            # Priority: Live configured providers first, then free models, then mock fallback
            capable.sort(key=lambda m: (
                0 if _is_configured(m.provider) else (2 if m.provider == "mock" else 1),
                0 if m.is_free else 1,
                -m.reasoning_tier.rank(),
                m.cost_per_1k_input_tokens
            ))
        else:
            # Production: Target models first (e.g. GPT-5.5/GPT-5.4/Gemini Pro), then highest capability
            capable.sort(key=lambda m: (
                0 if m.is_target and _is_configured(m.provider) else 1,
                0 if _is_configured(m.provider) else 1,
                -m.reasoning_tier.rank(),
                -m.coding_tier.rank()
            ))

        return capable
