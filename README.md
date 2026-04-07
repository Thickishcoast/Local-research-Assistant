# Local Research Console (Work on Progress)

A private, local research assistant built with **FastAPI**, **LangGraph**, **Gemini**, and **Tavily**.

Open it in your browser, ask questions, and get answers grounded in source materials fetched from the web.

## Core Purpose

This project is designed to fetch source materials from the web first, then synthesize answers from those sources.

## Features

- Gemini-powered planning and synthesis
- Tavily web search for fetching source materials
- Source deduplication and citation-ready outputs
- SQLite-backed thread memory
- Local-only access guard (`LOCAL_ONLY=true`)

## Tech Stack

- Python 3.12+
- FastAPI + Uvicorn
- LangGraph + LangChain
- langchain-google-genai
- Tavily Search (via langchain-community)
- SQLite checkpoint saver

## Project Structure

```text
src/
  agent/
    graph.py
    state.py
  api/
    main.py
    ui/
      index.html
      assets/
        app.js
        styles.css
```

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Create `.env` from `.env.example` and set values:

```env
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-2.5-flash
TAVILY_API_KEY=your_tavily_api_key
SQLITE_PATH=research_agent.sqlite
LOCAL_ONLY=true
```

## Run

```bash
uvicorn src.api.main:app --reload --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

## Privacy

For private/local usage:

- keep `LOCAL_ONLY=true`
- run with `--host 127.0.0.1`

## Troubleshooting

- If answers fail immediately, check `.env` keys.
- If you changed env values, restart Uvicorn.

## Roadmap

### Phase 1: Vector Memory

Add a vector database layer for long-term semantic recall.

- Keep checkpoint memory (thread state) as the source of truth.
- Store conversation turns or summaries as embeddings.
- Retrieve top-k semantically relevant past turns per query.
- Inject retrieved memory into prompts for better continuity.

### Phase 2: Document Reading (Upload + Web)

Enable the agent to read and use document files as sources.

- Support user-uploaded files (for example: PDF, TXT, DOCX, Markdown).
- Support document discovery from web links and pages.
- Extract, chunk, embed, and index document content.
- Use hybrid retrieval (vector retrieval + fresh web search) before synthesis.

### Phase 3: Multi-Agent Upgrade (Optional)

Introduce a dedicated web-research sub-agent when complexity grows.

- Keep the current single-agent flow for simple/fast queries.
- Add a specialized web-search/research agent for deeper investigations.
- Use planner + researcher + synthesizer roles for complex tasks.

### Phase 4: Character Memory Agent

Add a secondary agent that learns user preferences and communication style from conversation.

- Analyze conversation patterns (tone, depth, domain familiarity, goals).
- Convert insights into structured profile memories (not raw full chat dumps).
- Store profile memories in a vector database for semantic retrieval.
- Retrieve relevant profile memories at response time to personalize answers.

