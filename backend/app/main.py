import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.requests import Request

from app.config import get_settings
from app.routers import analysis, comparison, component_map, documents, emulation, export_import, files, findings, firmware, fuzzing, kernels, projects, sbom, terminal, uart
from app.utils.sandbox import PathTraversalError
from app.ai.adapter_manager import get_model_adapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    os.makedirs(settings.storage_root, exist_ok=True)
    os.makedirs(settings.emulation_kernel_dir, exist_ok=True)
    yield


app = FastAPI(
    title="Wairz",
    description="AI-Assisted Firmware Reverse Engineering & Security Assessment",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(firmware.router)
app.include_router(files.router)
app.include_router(analysis.router)
app.include_router(component_map.router)
app.include_router(findings.router)
app.include_router(documents.router)
app.include_router(sbom.router)
app.include_router(terminal.router)
app.include_router(emulation.router)
app.include_router(fuzzing.router)
app.include_router(kernels.router)
app.include_router(comparison.router)
app.include_router(export_import.router)
app.include_router(uart.router)


@app.exception_handler(PathTraversalError)
async def path_traversal_handler(request: Request, exc: PathTraversalError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.post("/api/v1/ai/test_generate")
async def ai_test_generate(payload: dict = Body(...)):
    """
    Test the configured model adapter.
    JSON body fields:
      - prompt: str
      - max_tokens: int (optional)
      - temperature: float (optional)
    """
    prompt = payload.get("prompt", "")
    if not prompt:
        return {"error": "prompt is required"}
    max_tokens = int(payload.get("max_tokens", 128))
    temperature = float(payload.get("temperature", 0.2))
    adapter = get_model_adapter()
    try:
        result = await adapter.generate(prompt, temperature=temperature, max_tokens=max_tokens)
    except Exception as exc:
        return {"error": str(exc)}
    return {"result": result}


@app.get("/health")
async def health():
    return {"status": "ok"}
