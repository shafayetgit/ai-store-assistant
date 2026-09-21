import asyncio
import logging
from typing import Any
import httpx
from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates text embeddings.
    Primary: LLM Gateway /embeddings endpoint.
    Fallback: Local Ollama (http://localhost:11434/api/embeddings).
    """

    def __init__(self):
        self._gateway_client: AsyncOpenAI | None = None
        self._gateway_loop: asyncio.AbstractEventLoop | None = None
        self.model = settings.PRIMARY_EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self.local_ollama_url = "http://localhost:11434"

    @property
    def gateway_client(self) -> AsyncOpenAI:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if self._gateway_client is None or self._gateway_loop != loop:
            self._gateway_loop = loop
            self._gateway_client = AsyncOpenAI(
                base_url=settings.LLM_GATEWAY_BASE_URL,
                api_key=settings.LLM_GATEWAY_API_KEY,
                timeout=settings.LLM_TIMEOUT_SECONDS,
            )
        return self._gateway_client
    async def get_embedding(self, text: str) -> list[float]:
        """
        Generates an embedding vector for a single text string.
        """
        embeddings = await self.get_embeddings([text])
        return embeddings[0] if embeddings else [0.0] * self.dimension

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generates embedding vectors for a batch of text strings.
        Tries gateway first; falls back to local Ollama if model not on remote gateway.
        """
        if not texts:
            return []

        # 1. Try Primary Gateway
        try:
            response = await self.gateway_client.embeddings.create(
                model=self.model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as gw_err:
            logger.warning(
                f"Gateway embeddings failed for '{self.model}': {gw_err}. "
                f"Attempting local Ollama at {self.local_ollama_url}..."
            )

        # 2. Fallback to Local Ollama
        try:
            results: list[list[float]] = []
            async with httpx.AsyncClient(timeout=30.0) as client:
                for text in texts:
                    res = await client.post(
                        f"{self.local_ollama_url}/api/embeddings",
                        json={"model": self.model, "prompt": text},
                    )
                    res.raise_for_status()
                    data = res.json()
                    results.append(data.get("embedding", [0.0] * self.dimension))
            return results

        except Exception as local_err:
            logger.error(f"Local Ollama embedding failed: {local_err}")
            raise RuntimeError(f"Could not generate embeddings using '{self.model}': {local_err}") from local_err


embedding_service = EmbeddingService()