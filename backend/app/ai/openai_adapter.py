"""OpenAI adapter for Wairz AI layer.

Provides a small wrapper class with generate() and stream_generate() methods
that match the expected interface used by Wairz's AI tooling layer.

This adapter uses the OpenAI Python client and supports both ChatCompletion
(chat-style models like gpt-3.5-turbo / gpt-4) and legacy Completion/Codex
models (code-davinci-002). It reads configuration from environment variables
via app.config.get_settings().
"""

import os
import asyncio
import logging
from typing import AsyncGenerator

import openai

from app.config import get_settings

logger = logging.getLogger(__name__)


class OpenAIAdapter:
    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.api_key = os.getenv("OPENAI_API_KEY") or getattr(settings, "openai_api_key", None)
        if not self.api_key:
            logger.info("OPENAI_API_KEY not set — OpenAI adapter will fail until configured.")
        openai.api_key = self.api_key
        # Allow overriding base URL for enterprise/proxy setups
        api_base = os.getenv("OPENAI_API_BASE") or getattr(settings, "openai_api_base", None)
        if api_base:
            openai.api_base = api_base
        self.model = model or os.getenv("OPENAI_MODEL") or "gpt-3.5-turbo"

    async def generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 512, system: str | None = None) -> str:
        """Synchronous (awaitable) single-response generation."""
        # Use chat API for gpt-* models
        loop = asyncio.get_event_loop()
        if self.model.startswith("gpt-") or "turbo" in self.model:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            def call_chat():
                return openai.ChatCompletion.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            resp = await loop.run_in_executor(None, call_chat)
            try:
                return resp.choices[0].message["content"]
            except Exception:
                logger.exception("OpenAI chat completion missing content")
                return ""
        else:
            def call_completion():
                return openai.Completion.create(
                    model=self.model,
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

            resp = await loop.run_in_executor(None, call_completion)
            try:
                return resp.choices[0].text
            except Exception:
                logger.exception("OpenAI completion missing text")
                return ""

    async def stream_generate(self, prompt: str, temperature: float = 0.2, max_tokens: int = 512, system: str | None = None) -> AsyncGenerator[str, None]:
        """Stream tokens from the OpenAI API as they arrive.

        Yields text chunks (may be partial tokens). Caller should concatenate them.
        """
        if self.model.startswith("gpt-") or "turbo" in self.model:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            # The OpenAI client is blocking; use run_in_executor to iterate
            def stream():
                return openai.ChatCompletion.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )

            loop = asyncio.get_event_loop()
            stream_iter = await loop.run_in_executor(None, stream)
            try:
                for event in stream_iter:
                    # Each event has choices[0].delta which may contain 'content'
                    delta = event.choices[0].delta
                    chunk = delta.get("content", "")
                    if chunk:
                        yield chunk
            except Exception:
                logger.exception("Error while streaming OpenAI chat completion")
                return
        else:
            def stream():
                return openai.Completion.create(
                    model=self.model,
                    prompt=prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                )

            loop = asyncio.get_event_loop()
            stream_iter = await loop.run_in_executor(None, stream)
            try:
                for event in stream_iter:
                    chunk = getattr(event.choices[0], "text", "")
                    if chunk:
                        yield chunk
            except Exception:
                logger.exception("Error while streaming OpenAI completion")
                return
