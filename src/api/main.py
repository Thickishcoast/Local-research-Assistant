"""FastAPI entrypoint for the local research web app."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from src.agent.graph import ResearchRuntime
from src.agent.state import build_fallback_answer, clamp_max_sources
from src.config import Settings


class RuntimeProtocol(Protocol):
    model_name: str

    def invoke(self, *, query: str, thread_id: str, max_sources: int) -> dict[str, Any]: ...

    def close(self) -> None: ...


class AskRequest(BaseModel):
    query: str = Field(min_length=1)
    thread_id: str | None = None
    max_sources: int = Field(default=5, ge=1, le=10)

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be blank")
        return cleaned


class SourceResponse(BaseModel):
    id: int
    title: str
    url: str
    snippet: str


class MetaResponse(BaseModel):
    model: str
    search_queries: list[str]
    source_count: int


class AskResponse(BaseModel):
    thread_id: str
    answer: str
    sources: list[SourceResponse]
    meta: MetaResponse


@dataclass
class _RuntimeHolder:
    runtime: RuntimeProtocol | None = None


def _is_local_client(host: str | None) -> bool:
    if not host:
        return False
    normalized = host.lower()
    if normalized in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return True
    if normalized.startswith("::ffff:127.0.0.1"):
        return True
    return False


def create_app(
    settings: Settings | None = None,
    runtime: RuntimeProtocol | None = None,
) -> FastAPI:
    settings = settings or Settings()
    holder = _RuntimeHolder(runtime=runtime)

    ui_root = Path(__file__).resolve().parent / "ui"
    ui_index = ui_root / "index.html"
    ui_assets = ui_root / "assets"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if holder.runtime is not None:
            holder.runtime.close()

    app = FastAPI(
        title="Local Research Console",
        version="2.0.0",
        description="Private local web app backed by LangGraph + Tavily + Gemini.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    if ui_assets.exists():
        app.mount("/ui-assets", StaticFiles(directory=str(ui_assets)), name="ui-assets")

    @app.middleware("http")
    async def local_only_guard(request: Request, call_next):
        if settings.local_only and not _is_local_client(request.client.host if request.client else None):
            return JSONResponse(
                status_code=403,
                content={"detail": "Local-only mode enabled. Access is restricted to this machine."},
            )
        return await call_next(request)

    def ensure_runtime() -> RuntimeProtocol:
        if holder.runtime is not None:
            return holder.runtime

        missing = settings.missing_required_for_research()
        if missing:
            raise RuntimeError(
                "App is missing required environment variables. "
                f"Please set: {', '.join(missing)}"
            )

        holder.runtime = ResearchRuntime(settings=settings)
        return holder.runtime

    @app.get("/")
    @app.get("/ui")
    async def ui_page() -> FileResponse:
        if not ui_index.exists():
            raise HTTPException(status_code=404, detail="UI files not found")
        return FileResponse(ui_index)

    @app.post("/ask", response_model=AskResponse, include_in_schema=False)
    async def ask(payload: AskRequest) -> AskResponse:
        thread_id = payload.thread_id or str(uuid4())
        max_sources = clamp_max_sources(payload.max_sources)

        try:
            active_runtime = ensure_runtime()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        try:
            state = active_runtime.invoke(
                query=payload.query,
                thread_id=thread_id,
                max_sources=max_sources,
            )
        except Exception as exc:  # pragma: no cover - network/runtime failures
            raise HTTPException(status_code=502, detail=f"Agent execution failed: {exc}") from exc

        answer = (state.get("final_answer") or "").strip() or build_fallback_answer(payload.query)
        raw_sources = state.get("sources") or []
        sources: list[SourceResponse] = [SourceResponse(**_coerce_source(item)) for item in raw_sources]

        return AskResponse(
            thread_id=thread_id,
            answer=answer,
            sources=sources,
            meta=MetaResponse(
                model=active_runtime.model_name,
                search_queries=list(state.get("search_queries") or []),
                source_count=len(sources),
            ),
        )

    return app


def _coerce_source(item: dict[str, Any]) -> dict[str, object]:
    return {
        "id": int(item.get("id", 0)),
        "title": str(item.get("title", "Untitled source")),
        "url": str(item.get("url", "")),
        "snippet": str(item.get("snippet", "")),
    }


app = create_app()