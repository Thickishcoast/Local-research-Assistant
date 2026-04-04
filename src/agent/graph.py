"""LangGraph construction and runtime helpers for the research agent."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from langchain_community.utilities.tavily_search import TavilySearchAPIWrapper
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.agent.state import (
    ResearchState,
    Source,
    build_fallback_answer,
    clamp_max_sources,
    dedupe_and_limit_sources,
    normalize_queries,
)
from src.config import Settings


class QueryPlanner(Protocol):
    def __call__(self, query: str) -> list[str]: ...


class WebSearcher(Protocol):
    def __call__(self, query: str, max_results: int) -> list[dict[str, Any]]: ...


class AnswerSynthesizer(Protocol):
    def __call__(
        self,
        query: str,
        sources: list[Source],
        previous_answer: str | None,
    ) -> str: ...


@dataclass(frozen=True)
class GraphDependencies:
    plan_queries: QueryPlanner
    search_web: WebSearcher
    synthesize_answer: AnswerSynthesizer
    model_name: str


class _SearchPlan(BaseModel):
    queries: list[str] = Field(
        min_length=2,
        max_length=4,
        description="2-4 focused web search queries for the user question",
    )


def _message_to_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text")
                if text:
                    chunks.append(str(text))
            else:
                chunks.append(str(part))
        return "\n".join(chunks)
    return str(content)


def make_gemini_planner(*, model_name: str, api_key: str) -> QueryPlanner:
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        api_key=api_key,
        temperature=0.4,
        convert_system_message_to_human=True,
    )
    structured_llm = llm.with_structured_output(_SearchPlan)

    def _plan(query: str) -> list[str]:
        messages = [
            SystemMessage(
                content=(
                    "You produce focused web-search queries. "
                    "Return 2 to 4 concise queries that maximize source coverage."
                )
            ),
            HumanMessage(content=f"User question:\n{query}"),
        ]
        result = structured_llm.invoke(messages)
        return result.queries

    return _plan


def make_tavily_searcher(*, api_key: str) -> WebSearcher:
    wrapper = TavilySearchAPIWrapper(tavily_api_key=api_key)

    def _search(query: str, max_results: int) -> list[dict[str, Any]]:
        return wrapper.results(
            query=query,
            max_results=max_results,
            search_depth="advanced",
            include_answer=False,
            include_raw_content=False,
            include_images=False,
        )

    return _search


def make_gemini_synthesizer(*, model_name: str, api_key: str) -> AnswerSynthesizer:
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        api_key=api_key,
        temperature=0,
        convert_system_message_to_human=True,
    )

    def _synthesize(query: str, sources: list[Source], previous_answer: str | None) -> str:
        source_lines = [
            f"[{source['id']}] {source['title']}\nURL: {source['url']}\nSnippet: {source['snippet']}"
            for source in sources
        ]
        sources_block = "\n\n".join(source_lines) if source_lines else "No web sources were retrieved."
        previous_context = previous_answer or "None"

        messages = [
            SystemMessage(
                content=(
                    "You are a research assistant. Prioritize provided sources when available. "
                    "You may use your own general knowledge to fill gaps. "
                    "Use inline citations like [1], [2] only for claims supported by the provided sources. "
                    "For claims from model knowledge, do not cite them and explicitly mark them as background knowledge."
                )
            ),
            HumanMessage(
                content=(
                    f"Question:\n{query}\n\n"
                    f"Previous answer in this thread:\n{previous_context}\n\n"
                    "Sources:\n"
                    + sources_block
                )
            ),
        ]
        response = llm.invoke(messages)
        return _message_to_text(response.content).strip()

    return _synthesize

def create_default_dependencies(settings: Settings) -> GraphDependencies:
    missing = settings.missing_required_for_research()
    if missing:
        raise ValueError(f"Missing required env vars: {', '.join(missing)}")

    gemini_key = settings.gemini_api_key.get_secret_value()  # type: ignore[union-attr]
    tavily_key = settings.tavily_api_key.get_secret_value()  # type: ignore[union-attr]
    model_name = settings.gemini_model or ""

    return GraphDependencies(
        plan_queries=make_gemini_planner(model_name=model_name, api_key=gemini_key),
        search_web=make_tavily_searcher(api_key=tavily_key),
        synthesize_answer=make_gemini_synthesizer(model_name=model_name, api_key=gemini_key),
        model_name=model_name,
    )


def compile_research_graph(
    dependencies: GraphDependencies,
    *,
    checkpointer: Any | None = None,
):
    """Compile the research StateGraph."""

    def plan_search(state: ResearchState) -> ResearchState:
        query = (state.get("query") or "").strip()
        errors: list[str] = []
        try:
            planned_queries = dependencies.plan_queries(query)
        except Exception as exc:  # pragma: no cover - hard to force from providers
            planned_queries = [query]
            errors.append(f"plan_search failed: {exc}")

        return {
            "search_queries": normalize_queries(planned_queries, query),
            "raw_results": [],
            "sources": [],
            "errors": errors,
        }

    def run_search(state: ResearchState) -> ResearchState:
        max_sources = clamp_max_sources(state.get("max_sources"), default=5)
        errors = list(state.get("errors", []))
        gathered: list[dict[str, Any]] = []

        for query in state.get("search_queries", []):
            try:
                items = dependencies.search_web(query, max_sources)
            except Exception as exc:
                errors.append(f"run_search failed for query `{query}`: {exc}")
                continue

            for item in items or []:
                if not isinstance(item, dict):
                    continue
                gathered.append(
                    {
                        "query": query,
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "content": item.get("content", ""),
                        "score": item.get("score", 0.0),
                    }
                )

        sources = dedupe_and_limit_sources(gathered, max_sources)
        return {
            "raw_results": gathered,
            "sources": sources,
            "errors": errors,
        }

    def synthesize(state: ResearchState) -> ResearchState:
        query = (state.get("query") or "").strip()
        sources = state.get("sources", [])
        errors = list(state.get("errors", []))
        previous_answer = state.get("final_answer")

        try:
            answer = dependencies.synthesize_answer(query, sources, previous_answer)
        except Exception as exc:
            errors.append(f"synthesize failed: {exc}")
            answer = ""

        if not answer.strip():
            answer = build_fallback_answer(query)

        return {
            "final_answer": answer,
            "errors": errors,
        }

    builder = StateGraph(ResearchState)
    builder.add_node("plan_search", plan_search)
    builder.add_node("run_search", run_search)
    builder.add_node("synthesize", synthesize)

    builder.add_edge(START, "plan_search")
    builder.add_edge("plan_search", "run_search")
    builder.add_edge("run_search", "synthesize")
    builder.add_edge("synthesize", END)

    return builder.compile(checkpointer=checkpointer)

class ResearchRuntime:
    """Runtime wrapper that owns the compiled graph and checkpointer lifecycle."""

    def __init__(
        self,
        settings: Settings,
        *,
        dependencies: GraphDependencies | None = None,
    ) -> None:
        self.settings = settings
        self.dependencies = dependencies or create_default_dependencies(settings)
        self.model_name = self.dependencies.model_name

        sqlite_path = Path(settings.sqlite_path).expanduser().resolve()
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)

        self._stack = ExitStack()
        self._checkpointer = self._stack.enter_context(
            SqliteSaver.from_conn_string(str(sqlite_path))
        )
        self.graph = compile_research_graph(
            self.dependencies,
            checkpointer=self._checkpointer,
        )

    def close(self) -> None:
        self._stack.close()

    def invoke(self, *, query: str, thread_id: str, max_sources: int) -> ResearchState:
        state_update: ResearchState = {
            "query": query,
            "thread_id": thread_id,
            "max_sources": clamp_max_sources(max_sources),
        }
        config = {"configurable": {"thread_id": thread_id}}

        output = self.graph.invoke(state_update, config=config)
        if not isinstance(output, dict):
            raise RuntimeError("Graph returned unexpected output type.")
        return output