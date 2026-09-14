import os
import json
import time
from typing import Dict, Any, Optional
import httpx
from src.llm.base import BaseLLMAdapter
from src.llm.schemas import LLMRequest, LLMResponse, ModelCapability
from config.settings import settings


class OpenAIAdapter(BaseLLMAdapter):
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_key = settings.OPENAI_API_KEY or os.getenv("OPENAI_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    async def health_check(self) -> bool:
        if not self.is_available():
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"}
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def generate(self, request: LLMRequest, model: ModelCapability) -> LLMResponse:
        start_time = time.time()
        # Fallback to dev model if target model is requested but unavailable in live API
        target_model = model.id
        if target_model in ["gpt-5.5", "gpt-5.4"]:
            target_model = "gpt-4o-mini"  # safe development fallback mapping

        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        payload: Dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "temperature": request.temperature,
        }
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens

        if request.response_schema:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            if resp.status_code != 200:
                raise RuntimeError(f"OpenAI API Error ({resp.status_code}): {resp.text}")
            
            data = resp.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
            
            cost = (tokens_in / 1000.0 * model.cost_per_1k_input_tokens) + (tokens_out / 1000.0 * model.cost_per_1k_output_tokens)
            structured_data = None
            if request.response_schema:
                try:
                    structured_data = json.loads(content)
                except Exception:
                    pass

            latency = (time.time() - start_time) * 1000
            return LLMResponse(
                content=content,
                structured_data=structured_data,
                model_used=model.id,
                provider_used="openai",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=cost,
                latency_ms=latency
            )
