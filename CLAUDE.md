# CLAUDE.md — Wairz Codebase Guide

This file is for AI agents (Claude Code, etc.) working on the Wairz codebase. It describes the architecture, conventions, and patterns you need to follow when making changes.

**What is Wairz?** An open-source, browser-based firmware reverse engineering and security assessment platform. Users upload firmware, the tool unpacks it, and provides a unified interface for file inspection, static analysis, emulation, and automated security checks.

---

## Architecture Overview

```
Claude Code / Claude Desktop
        │
        │ MCP (stdio)
        ▼
┌─────────────────┐     ┌──────────────────────────────────┐
│   wairz-mcp     │────▶│         FastAPI Backend           │
│  (MCP server)   │     │                                    │
│  60+ tools      │     │  Services: firmware, file,         │
│                 │     │  analysis, emulation, fuzzing,     │
│  Entry point:   │     │  sbom, uart, finding, export...    │
│  wairz-mcp CLI  │     │                                    │
└─────────────────┘     │  Ghidra headless · QEMU · AFL++    │
                        └──────────┬───────────────────────┘
                                   │
┌──────────────┐    ┌──────────────┼──────────────┐
│   React SPA  │───▶│  PostgreSQL  │  Redis       │
│  (Frontend)  │    │              │              │
└──────────────┘    └──────────────┴──────────────┘

Host machine (optional):
  wairz-uart-bridge.py ←─ TCP:9999 ─→ Docker backend
```

- **Frontend:** React 19 + Vite + TypeScript, shadcn/ui + Tailwind, Monaco Editor, ReactFlow, xterm.js, Zustand
- **Backend:** Python 3.12 + FastAPI (async), SQLAlchemy 2.0 (async) + Alembic, pydantic-settings
- **MCP Server:** `wairz-mcp` CLI entry point (`app.mcp_server:main`), stdio transport, 60+ tools
- **Database:** PostgreSQL 16 (JSONB for analysis cache)
- **Containers:** Docker Compose — backend, postgres, redis, emulation (QEMU), fuzzing (AFL++)

---

## Directory Structure

```
wairz/
├── backend/
│   ├── pyproject.toml           # Entry point: wairz-mcp
│   ├── alembic/versions/        # Database migrations (auto-run on container start)
│   └── app/
│       ├── main.py              # FastAPI app + router registration
│       ├── config.py            # Settings via pydantic-settings
│       ├── database.py          # Async engine, session factory, get_db dependency
│       ├── mcp_server.py        # MCP server with dynamic project switching
│       ├── models/              # SQLAlchemy ORM models
│       ├── schemas/             # Pydantic request/response schemas
│       ├── routers/             # FastAPI REST endpoint routers
│       ├── services/            # Business logic layer
│       ├── workers/             # Background tasks (firmware unpacking)
│       ├── ai/
│       │   ├── __init__.py      # Tool registry factory — registers all tool categories
│       │   ├── tool_registry.py # ToolContext + ToolRegistry framework
│       │   ├── system_prompt.py # MCP system prompt for Claude
│       │   └── tools/           # Tool handlers by category
│       └── utils/
│           ├── sandbox.py       # Path traversal prevention (CRITICAL)
│           └── truncation.py    # Output truncation (30KB max)
├── frontend/
│   └── src/
│       ├── pages/               # Route pages, registered in App.tsx
│       ├── components/          # UI components organized by feature
│       ├── api/                 # Axios API client functions
│       ├── stores/              # Zustand state management
│       └── types/               # TypeScript type definitions
├── ghidra/
│   ├── Dockerfile
│   └── scripts/                 # Custom Java analysis scripts for headless Ghidra
├── emulation/
│   ├── Dockerfile               # QEMU + kernels (ARM, MIPS, MIPSel, AArch64)
│   └── scripts/                 # start-user-mode.sh, start-system-mode.sh, serial-exec.sh
├── fuzzing/
│   └── Dockerfile               # AFL++ with QEMU mode
└── scripts/
    └── wairz-uart-bridge.py     # Host-side serial bridge (standalone, pyserial only)
```

---

## LLM Integration — OpenAI (Codex/ChatGPT) & local llama.cpp (ggml)

This branch (`feature/add-openai-llama-support`) includes adapters and wiring so the backend can use either an external OpenAI model (Codex/ChatGPT) or a local LLM server (llama.cpp / ggml via an HTTP server). The goal: boot the stack with Docker Compose and be able to call the configured model (OpenAI or local) from the backend immediately.

What’s included on this branch
- backend/app/ai/openai_adapter.py — OpenAI adapter (supports chat-style and legacy completion/Codex models)
- backend/app/ai/llama_adapter.py — HTTP-first adapter for local model servers (tries common endpoints used by text-generation-webui / oobabooga)
- backend/app/ai/adapter_manager.py — runtime chooser based on MODEL_BACKEND env var
- backend/app/config.py — settings for MODEL_BACKEND, OPENAI_*, LOCAL_LLM_URL
- docker-compose.yml — environment wiring and an optional (commented) local-llm service example
- backend/pyproject.toml — openai python client added
- A test endpoint to exercise the configured adapter: POST /api/v1/ai/test_generate (added to main)

Quick design notes
- The backend talks to the model via one of two adapters: OpenAI (remote, billable) or local-llm (HTTP server running in another container). This keeps the backend image small and avoids building large native LLM toolchains into the backend container.
- Local model server is recommended to be run in a separate container (example: text-generation-webui / oobabooga). That container can be configured to use CUDA on GPU hosts or ggml/gguf CPU-only models on CPU-only hosts.
- Security: API keys are not committed. Use .env for local testing or Docker secrets for production.

Quickstart — make the branch self-contained and runnable

1) Prepare environment file (.env)

Create a .env file at the repo root (do NOT commit it). Minimum values for quick test using OpenAI:

```env
# Backend/database
DATABASE_URL=postgresql+asyncpg://wairz:wairz@postgres:5432/wairz
REDIS_URL=redis://redis:6379/0

# LLM backend selection: claude | openai | local-llama
MODEL_BACKEND=openai

# OpenAI (if using OpenAI)
OPENAI_API_KEY=sk_...   # put your key here
OPENAI_MODEL=gpt-3.5-turbo
OPENAI_API_BASE=

# Local LLM (if using local-llama)
#LOCAL_LLM_URL=http://local-llm:8080

# Other defaults (keep existing values or adjust as needed)
UART_BRIDGE_HOST=host.docker.internal
UART_BRIDGE_PORT=9999
STORAGE_ROOT=/data/firmware
```

2) Start required services (Postgres + Redis + Backend)

- Build and start (OpenAI mode):

```bash
docker compose build backend
docker compose up -d postgres redis backend
```

- Verify backend is running:

```bash
docker compose ps
curl http://localhost:8000/health
# -> {"status":"ok"}
```

3) Test the model adapter (OpenAI example)

Call the test endpoint in the backend (the backend will forward to OpenAI):

```bash
curl -s -X POST http://localhost:8000/api/v1/ai/test_generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Write a one-line python program that prints Hello World","max_tokens":60}' | jq
```

If OPENAI_API_KEY is set and billing is active you should receive a short completion from the OpenAI model.

4) Optional: Run a local llama.cpp-compatible server (CPU fallback / GPU preferred)

If you prefer to run models locally (no external API calls), enable the optional `local-llm` service in docker-compose.yml (it is commented out by default). The example uses text-generation-webui (oobabooga) which exposes a simple HTTP API compatible with our adapter.

- Steps:
  1. Uncomment the `local-llm` service in docker-compose.yml (we included a commented example). This example maps `./models` on the host to `/data/models` in the container — place your ggml/gguf model files in `./models`.
  2. Update your .env:

```env
MODEL_BACKEND=local-llama
LOCAL_LLM_URL=http://local-llm:8080
```

  3. Start the local model service (first time may download dependencies in that container):

```bash
docker compose up -d local-llm
```

  4. Start the backend (or restart it so it picks up the env changes):

```bash
docker compose up -d --build backend
```

  5. Test the adapter with the same curl call to `/api/v1/ai/test_generate` — the backend will call the local LLM server.

GPU notes
- If you have an NVIDIA GPU and installed the NVIDIA Container Toolkit, configure the model container to access the GPU (example `runtime: nvidia` and `NVIDIA_VISIBLE_DEVICES=all`, `NVIDIA_DRIVER_CAPABILITIES=compute,utility,graphics`). The example local-llm service in docker-compose.yml includes commented guidance.
- If no GPU is available the model container will run CPU-only and use ggml/gguf models — expect slower performance and high memory use for larger models.

Security & cost warnings
- OpenAI requests are billable. Do not send private firmware or secrets to OpenAI without explicit consent — prompts and content are transmitted to the provider.
- Do NOT commit OPENAI_API_KEY or any secret to the repository. Use .env for local dev and Docker secrets for production.

Adapter test endpoint (for quick verification)
- POST /api/v1/ai/test_generate
  - JSON body: {"prompt": "...", "max_tokens": 128, "temperature": 0.2}
  - Returns: {"result": "..."} or {"error": "..."}

Example:

```bash
curl -s -X POST http://localhost:8000/api/v1/ai/test_generate \
  -H "Content-Type: application/json" \
  -d '{"prompt":"Say hello","max_tokens":40}' | jq
```

Troubleshooting
- If the backend returns errors about the adapter:
  - Confirm MODEL_BACKEND is set correctly in .env
  - For openai: confirm OPENAI_API_KEY and OPENAI_MODEL are set and valid
  - For local-llama: confirm LOCAL_LLM_URL matches the local model service address and that the model service is healthy
- Inspect backend logs:
  - docker compose logs -f backend

---

## How to Add Things

### Adding a New MCP Tool

1. Create or edit a handler in `backend/app/ai/tools/<category>.py`:
   ```python
   async def _handle_my_tool(input: dict, context: ToolContext) -> str:
       # Available on context: project_id, firmware_id, extracted_path, db
       path = context.resolve_path(input.get("path", "/"))  # validates against sandbox
       # ... do work ...
       return "result string (max 30KB, truncated automatically)"
   ```
2. Register in the same file's `register_<category>_tools(registry)` function:
   ```python
   registry.register(name="my_tool", description="...", input_schema={...}, handler=_handle_my_tool)
   ```
3. If it's a new category file, import and call `register_<category>_tools(registry)` in `backend/app/ai/__init__.py`.

---

## Critical Rules

### Security

1. **Path traversal prevention is mandatory.** Every file access must be validated via `app/utils/sandbox.py` (`os.path.realpath()` + prefix check against the extracted root). The MCP `ToolContext` helpers perform this validation — use them.
2. **Never execute firmware binaries on the host.** Emulation runs inside an isolated QEMU Docker container. Fuzzing runs inside an isolated AFL++ Docker container. Both have resource limits (memory/cpu) and are isolated from the host.
3. **No API keys stored in the backend.** The Anthropic/OpenAI API key should not be stored in the repository. Use .env for local dev and Docker secrets for production.

### Performance

1. **Cache Ghidra decompilations** — each run takes 30-120s. Cached by binary hash + function name in the `analysis_cache` table.
2. **Cache radare2 analysis** — `aaa` can take 10-30s. LRU session caching in the analysis service.
3. **Lazy-load the file tree** — firmware can have 10K+ files. Load children on expand, never the full tree at once.
4. **Truncate MCP tool outputs** — keep under 30KB (`app/utils/truncation.py`). Large outputs break MCP clients.
5. **Firmware unpacking is non-blocking** — the unpack endpoint returns 202 and runs `asyncio.create_task()`. The frontend polls every 2s until status changes from "unpacking".

---

(End of file)
