import asyncio
import logging
import threading
import weakref
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
        self._lock = threading.Lock()
        self._gateway_clients: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, AsyncOpenAI] = weakref.WeakKeyDictionary()
        self._default_gateway: AsyncOpenAI | None = None
        self.model = settings.PRIMARY_EMBEDDING_MODEL
        self.dimension = settings.EMBEDDING_DIMENSION
        self.local_ollama_url = "http://localhost:11434"

    @property
    def gateway_client(self) -> AsyncOpenAI:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None:
            with self._lock:
                if loop not in self._gateway_clients:
                    self._gateway_clients[loop] = AsyncOpenAI(
                        base_url=settings.LLM_GATEWAY_BASE_URL,
                        api_key=settings.LLM_GATEWAY_API_KEY,
                        timeout=settings.LLM_TIMEOUT_SECONDS,
                    )
                return self._gateway_clients[loop]

        with self._lock:
            if self._default_gateway is None:
                self._default_gateway = AsyncOpenAI(
                    base_url=settings.LLM_GATEWAY_BASE_URL,
                    api_key=settings.LLM_GATEWAY_API_KEY,
                    timeout=settings.LLM_TIMEOUT_SECONDS,
                )
            return self._default_gateway

    async def get_embedding(self, text: str) -> list[float]:
        """
        Generates an embedding vector for a single text string.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return [0.0] * self.dimension
        embeddings = await self.get_embeddings([cleaned])
        return embeddings[0] if embeddings else [0.0] * self.dimension

    async def get_embeddings(self, texts: list[str]) -> list[list[float]]:
        """
        Generates embedding vectors for a batch of text strings.
        Tries gateway first; falls back to local Ollama if model not on remote gateway.
        """
        if not texts:
            return []

        # Filter empty strings
        sanitized_texts = [t.strip() or " " for t in texts]

        # 1. Try Primary Gateway
        try:
            response = await self.gateway_client.embeddings.create(
                model=self.model,
                input=sanitized_texts,
            )
            logger.info(f"Successfully generated embeddings via gateway for model '{self.model}'.")
            return [item.embedding for item in response.data]
        except Exception as gw_err:
            logger.warning(
                f"Gateway embeddings failed for '{self.model}': {gw_err}. "
                f"Attempting local Ollama at {self.local_ollama_url}..."
            )

        # 2. Fallback to Local Ollama
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Try modern batch /api/embed first
                try:
                    res = await client.post(
                        f"{self.local_ollama_url}/api/embed",
                        json={"model": self.model, "input": sanitized_texts},
                    )
                    if res.status_code == 200:
                        data = res.json()
                        if "embeddings" in data:
                            return data["embeddings"]
                except Exception:
                    pass

                # Fallback to legacy single-item /api/embeddings
                results: list[list[float]] = []
                for text in sanitized_texts:
                    res = await client.post(
                        f"{self.local_ollama_url}/api/embeddings",
                        json={"model": self.model, "prompt": text},
                    )
                    res.raise_for_status()
                    data = res.json()
                    emb = data.get("embedding") or (data.get("embeddings")[0] if data.get("embeddings") else None) or ([0.0] * self.dimension)
                    results.append(emb)
                return results

        except Exception as local_err:
            logger.error(f"Local Ollama embedding failed: {local_err}")
            raise RuntimeError(f"Could not generate embeddings using '{self.model}': {local_err}") from local_err


embedding_service = EmbeddingService()