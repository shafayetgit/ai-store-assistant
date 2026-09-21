import asyncio
import logging
from collections.abc import AsyncGenerator
from typing import Any
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMClient:
    """
    Async client for OpenAI-compatible LLM Gateway with streaming and tool calling.
    Primary: Private llm-gateway (http://localhost:8002/api/v1).
    Secondary: Fallback cloud provider (if enabled).
    """

    def __init__(self):
        self._primary_client: AsyncOpenAI | None = None
        self._primary_loop: asyncio.AbstractEventLoop | None = None
        self._fallback_client: AsyncOpenAI | None = None
        self._fallback_loop: asyncio.AbstractEventLoop | None = None

        self.primary_model = settings.PRIMARY_LLM_MODEL
        self.fallback_enabled = settings.FALLBACK_ENABLED
        self.fallback_model = settings.FALLBACK_LLM_MODEL

    @property
    def primary_client(self) -> AsyncOpenAI:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if self._primary_client is None or self._primary_loop != loop:
            self._primary_loop = loop
            self._primary_client = AsyncOpenAI(
                base_url=settings.LLM_GATEWAY_BASE_URL,
                api_key=settings.LLM_GATEWAY_API_KEY,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        return self._primary_client

    @property
    def fallback_client(self) -> AsyncOpenAI | None:
        if not self.fallback_enabled or not settings.OPENAI_API_KEY:
            return None

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if self._fallback_client is None or self._fallback_loop != loop:
            self._fallback_loop = loop
            self._fallback_client = AsyncOpenAI(
                api_key=settings.OPENAI_API_KEY,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        return self._fallback_client

    async def chat_completion(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> dict[str, Any]:
        """
        Executes a non-streaming chat completion with function calling.
        """
        kwargs: dict[str, Any] = {
            "model": self.primary_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice

        try:
            response = await self.primary_client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message

            tool_calls = []
            if message.tool_calls:
                for tc in message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        }
                    })

            return {
                "role": message.role,
                "content": message.content or "",
                "tool_calls": tool_calls,
                "finish_reason": choice.finish_reason,
            }

        except Exception as primary_err:
            logger.warning(f"Primary LLM Gateway call failed: {primary_err}")
            if self.fallback_enabled and self.fallback_client:
                logger.info(f"Flipping to fallback model: {self.fallback_model}")
                kwargs["model"] = self.fallback_model
                response = await self.fallback_client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                message = choice.message
                return {
                    "role": message.role,
                    "content": message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": tc.type,
                            "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                        }
                        for tc in (message.tool_calls or [])
                    ],
                    "finish_reason": choice.finish_reason,
                }
            raise primary_err

    async def stream_chat_completion(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.2,
        max_tokens: int = 1024,
    ) -> AsyncGenerator[str, None]:
        """
        Streams token chunks as they arrive for real-time SSE Web Chat responses.
        """
        try:
            stream = await self.primary_client.chat.completions.create(
                model=self.primary_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as primary_err:
            logger.warning(f"Primary stream failed: {primary_err}")
            if self.fallback_enabled and self.fallback_client:
                logger.info("Falling back to secondary stream...")
                stream = await self.fallback_client.chat.completions.create(
                    model=self.fallback_model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )
                async for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content
            else:
                raise primary_err


llm_client = LLMClient()