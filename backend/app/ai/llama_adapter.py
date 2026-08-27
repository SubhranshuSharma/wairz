from typing import AsyncGenerator
import asyncio
import logging
import os
import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)


class LlamaAdapter:
    """Adapter that calls a local LLM server over HTTP.

    Tries common endpoints used by text-generation-webui / ggml HTTP servers:
    - POST {url}/api/predict with JSON {"inputs": prompt, "parameters": {...}}
    - POST {url}/generate with JSON {"prompt": prompt, ...}

    Configure the target URL via LOCAL_LLM_URL environment variable or settings.local_llm_url.
    """

    def __init__(self, base_url: str | None = None):
        settings = get_settings()
        self.base_url = (
            base_url or os.getenv("LOCAL_LLM_URL") or getattr(settings, "local_llm_url", None)
        )
        if not self.base_url:
            logger.info("LOCAL_LLM_URL not set — Llama adapter will fail until configured.")
        # normalize
        if self.base_url and self.base_url.endswith("/"):
            self.base_url = self.base_url[:-1]
        self.client = httpx.Client(timeout=60.0)

    async def generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 512, system: str | None = None) -> str:
        if not self.base_url:
            raise RuntimeError("LOCAL_LLM_URL not configured")

        payload = {"inputs": prompt, "parameters": {"temperature": temperature, "max_new_tokens": max_tokens}}

        # Try common endpoints
        endpoints = ["/api/predict", "/api/generate", "/generate"]

        loop = asyncio.get_event_loop()

        def do_request(path: str):
            try:
                url = self.base_url + path
                resp = self.client.post(url, json=payload)
                resp.raise_for_status()
                return resp.json()
            except Exception as exc:
                logger.debug("Request to %s failed: %s", path, exc)
                return None

        for ep in endpoints:
            result = await loop.run_in_executor(None, do_request, ep)
            if result:
                # Try to extract text from known shapes
                # text-generation-webui / oobabooga : {"generated_text": "..."} or {"results": [{"generated_text": "..."}]}
                if isinstance(result, dict):
                    if "generated_text" in result:
                        return result["generated_text"]
                    if "results" in result and isinstance(result["results"], list):
                        first = result["results"][0]
                        if isinstance(first, dict) and "generated_text" in first:
                            return first["generated_text"]
                    # Hugging Face style: {"generated_text": ...}
                    if "text" in result and isinstance(result["text"], str):
                        return result["text"]
                    # If the API returns 'data' with text
                    if "data" in result:
                        # data may be a list of dicts
                        data = result["data"]
                        if isinstance(data, list) and data and isinstance(data[0], dict):
                            for k in ("generated_text", "text", "content"):
                                if k in data[0]:
                                    return data[0][k]
                        if isinstance(data, str):
                            return data
                # If unknown shape, try raw text
                if isinstance(result, str):
                    return result
        raise RuntimeError("Local LLM server did not return a usable response")

    async def stream_generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 512, system: str | None = None) -> AsyncGenerator[str, None]:
        """Attempt a streaming generate by connecting to an SSE or chunked endpoint.

        Many local servers provide streaming via /api/stream or /api/predict with stream=True.
        We'll attempt to connect to /api/stream and yield text lines as they arrive.
        If streaming is not available, fall back to a single generate() call and yield the full text.
        """
        if not self.base_url:
            raise RuntimeError("LOCAL_LLM_URL not configured")

        stream_endpoints = ["/api/stream", "/api/predict?stream=true", "/stream"]

        async with httpx.AsyncClient(timeout=None) as aclient:
            for ep in stream_endpoints:
                url = self.base_url + ep
                try:
                    async with aclient.stream("POST", url, json={"inputs": prompt, "parameters": {"temperature": temperature, "max_new_tokens": max_tokens}}) as resp:
                        if resp.status_code != 200:
                            continue
                        async for chunk in resp.aiter_text():
                            if chunk:
                                yield chunk
                        return
                except Exception as exc:
                    logger.debug("Streaming attempt to %s failed: %s", url, exc)
                    continue
        # Fallback
        text = await self.generate(prompt, temperature=temperature, max_tokens=max_tokens, system=system)
        yield text
