import os
import json
import time
from typing import Dict, Any
import httpx
from src.llm.base import BaseLLMAdapter
from src.llm.schemas import LLMRequest, LLMResponse, ModelCapability
from config.settings import settings


class GeminiAdapter(BaseLLMAdapter):
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")

    def is_available(self) -> bool:
        key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        return bool(key and len(key) > 5)

    async def health_check(self) -> bool:
        return self.is_available()

    async def generate(self, request: LLMRequest, model: ModelCapability) -> LLMResponse:
        start_time = time.time()
        api_key = settings.GEMINI_API_KEY or os.getenv("GEMINI_API_KEY", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model.id}:generateContent?key={api_key}"
        
        contents = []
        for m in request.messages:
            role = "user" if m.role in ["user", "system"] else "model"
            contents.append({"role": role, "parts": [{"text": m.content}]})

        payload: Dict[str, Any] = {"contents": contents}
        if request.response_schema:
            payload["generationConfig"] = {
                "response_mime_type": "application/json"
            }

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Gemini API Error ({resp.status_code}): {resp.text}")
            data = resp.json()
            text = data["candidates"][0]["content"]["parts"][0]["text"]
            structured_data = None
            if request.response_schema:
                try:
                    clean = text.strip().removeprefix("```json").removesuffix("```").strip()
                    structured_data = json.loads(clean)
                except Exception:
                    pass
            latency = (time.time() - start_time) * 1000
            return LLMResponse(
                content=text,
                structured_data=structured_data,
                model_used=model.id,
                provider_used="gemini",
                tokens_in=len(str(contents)) // 4,
                tokens_out=len(text) // 4,
                cost_usd=0.0,
                latency_ms=latency
            )


class GroqAdapter(BaseLLMAdapter):
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_key = settings.GROQ_API_KEY or os.getenv("GROQ_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    async def health_check(self) -> bool:
        return self.is_available()

    async def generate(self, request: LLMRequest, model: ModelCapability) -> LLMResponse:
        start_time = time.time()
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        payload = {
            "model": model.id,
            "messages": messages,
            "temperature": request.temperature
        }
        if request.response_schema:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload
            )
            if resp.status_code != 200:
                raise RuntimeError(f"Groq API Error ({resp.status_code}): {resp.text}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            tokens_in = usage.get("prompt_tokens", 0)
            tokens_out = usage.get("completion_tokens", 0)
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
                provider_used="groq",
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=0.0,
                latency_ms=latency
            )


class OpenRouterAdapter(BaseLLMAdapter):
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.api_key = settings.OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY", "")

    def is_available(self) -> bool:
        return bool(self.api_key and len(self.api_key) > 5)

    async def health_check(self) -> bool:
        return self.is_available()

    async def generate(self, request: LLMRequest, model: ModelCapability) -> LLMResponse:
        start_time = time.time()
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        payload = {
            "model": model.id,
            "messages": messages,
            "temperature": request.temperature
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload
            )
            if resp.status_code != 200:
                raise RuntimeError(f"OpenRouter API Error ({resp.status_code}): {resp.text}")
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            structured_data = None
            if request.response_schema:
                try:
                    clean = content.strip().removeprefix("```json").removesuffix("```").strip()
                    structured_data = json.loads(clean)
                except Exception:
                    pass
            latency = (time.time() - start_time) * 1000
            return LLMResponse(
                content=content,
                structured_data=structured_data,
                model_used=model.id,
                provider_used="openrouter",
                tokens_in=len(str(messages)) // 4,
                tokens_out=len(content) // 4,
                cost_usd=0.0,
                latency_ms=latency
            )


class OllamaAdapter(BaseLLMAdapter):
    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.base_url = settings.OLLAMA_BASE_URL

    def is_available(self) -> bool:
        return bool(self.base_url)

    async def health_check(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def generate(self, request: LLMRequest, model: ModelCapability) -> LLMResponse:
        start_time = time.time()
        messages = [{"role": m.role, "content": m.content} for m in request.messages]
        payload = {
            "model": model.id,
            "messages": messages,
            "stream": False
        }
        if request.response_schema:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama API Error ({resp.status_code}): {resp.text}")
            data = resp.json()
            content = data.get("message", {}).get("content", "")
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
                provider_used="ollama",
                tokens_in=data.get("prompt_eval_count", len(str(messages)) // 4),
                tokens_out=data.get("eval_count", len(content) // 4),
                cost_usd=0.0,
                latency_ms=latency
            )
