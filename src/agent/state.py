"""State models and transformation helpers for the research graph."""

from __future__ import annotations

from typing import TypedDict

DEFAULT_FALLBACK_ANSWER = (
    "I could not find enough trustworthy web results to answer that question yet. "
    "Please try rephrasing your query or broadening the topic."
)


class RawSearchResult(TypedDict, total=False):
    """Raw, normalized search result before URL dedupe."""

    query: str
    title: str
    url: str
    content: str
    score: float


class Source(TypedDict):
    """Source object returned by API."""

    id: int
    title: str
    url: str
    snippet: str


class ResearchState(TypedDict, total=False):
    """LangGraph state shape for the research workflow."""

    query: str
    thread_id: str
    max_sources: int
    search_queries: list[str]
    raw_results: list[RawSearchResult]
    final_answer: str
    sources: list[Source]
    errors: list[str]


def clamp_max_sources(value: int | None, default: int = 5) -> int:
    """Clamp the source count between 1 and 10."""
    if value is None:
        return default
    return min(10, max(1, int(value)))


def normalize_queries(planned: list[str] | None, fallback_query: str) -> list[str]:
    """Normalize planner output to 2-4 clean, deduplicated queries."""
    fallback_query = fallback_query.strip()
    cleaned: list[str] = []
    seen: set[str] = set()

    for candidate in planned or []:
        text = candidate.strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)

    if not cleaned:
        cleaned = [fallback_query]

    if len(cleaned) == 1:
        cleaned.append(f"{fallback_query} overview")

    return cleaned[:4]


def _truncate_snippet(value: str, limit: int = 350) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def dedupe_and_limit_sources(
    raw_results: list[RawSearchResult],
    max_sources: int,
) -> list[Source]:
    """Dedupe by URL and keep top N results by score (desc)."""
    # Keep stable ordering for equal scores by preserving original index.
    ranked: list[tuple[int, float, RawSearchResult]] = []
    for idx, item in enumerate(raw_results):
        score = float(item.get("score", 0.0) or 0.0)
        ranked.append((idx, score, item))

    ranked.sort(key=lambda x: (-x[1], x[0]))

    seen_urls: set[str] = set()
    sources: list[Source] = []

    for _, _, item in ranked:
        url = (item.get("url") or "").strip()
        if not url:
            continue
        dedupe_key = url.rstrip("/").lower()
        if dedupe_key in seen_urls:
            continue
        seen_urls.add(dedupe_key)

        title = (item.get("title") or "Untitled source").strip()
        snippet = _truncate_snippet(item.get("content") or "")

        sources.append(
            {
                "id": len(sources) + 1,
                "title": title,
                "url": url,
                "snippet": snippet,
            }
        )

        if len(sources) >= max_sources:
            break

    return sources


def build_fallback_answer(query: str) -> str:
    """Create a safe fallback answer when usable sources are unavailable."""
    if not query.strip():
        return DEFAULT_FALLBACK_ANSWER
    return f"{DEFAULT_FALLBACK_ANSWER} (query: {query.strip()})"