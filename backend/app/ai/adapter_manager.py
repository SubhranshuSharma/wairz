from typing import Any
import os

from app.config import get_settings


def get_model_adapter() -> Any:
    """
    Returns an adapter instance based on MODEL_BACKEND / settings.
    Supported backends: 'openai', 'local-llama', 'claude' (existing default).
    """
    settings = get_settings()
    backend = os.getenv("MODEL_BACKEND", settings.model_backend or "claude").lower()

    if backend == "openai":
        from app.ai.openai_adapter import OpenAIAdapter

        return OpenAIAdapter(model=os.getenv("OPENAI_MODEL", settings.openai_model))
    if backend in ("local-llama", "llama", "local"):
        from app.ai.llama_adapter import LlamaAdapter

        return LlamaAdapter(base_url=os.getenv("LOCAL_LLM_URL", settings.local_llm_url))
    # Fallback: attempt existing Claude adapter if present
    try:
        from app.ai.claude_adapter import ClaudeAdapter  # may not exist in this fork

        return ClaudeAdapter()
    except Exception:
        raise RuntimeError(f"No adapter available for backend '{backend}'")
