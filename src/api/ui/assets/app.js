const STORAGE_KEY = "local_research_history_v2";

const queryEl = document.getElementById("query");
const runBtn = document.getElementById("run-btn");
const clearHistoryBtn = document.getElementById("clear-history-btn");
const newTopicBtn = document.getElementById("new-topic-btn");
const statusEl = document.getElementById("status");
const answerEl = document.getElementById("answer");
const sourcesEl = document.getElementById("sources");
const topicPill = document.getElementById("topic-pill");
const historyListEl = document.getElementById("history-list");

let topics = [];
let activeTopicId = null;

function setStatus(message) {
  statusEl.textContent = message;
}

function trimTitle(value, maxLen = 58) {
  const clean = value.replace(/\s+/g, " ").trim();
  if (clean.length <= maxLen) {
    return clean;
  }
  return clean.slice(0, maxLen - 3).trimEnd() + "...";
}

function formatTime(iso) {
  const date = new Date(iso);
  return date.toLocaleString();
}

function saveTopics() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(topics));
  } catch {
    // Ignore storage failures.
  }
}

function normalizeTopic(raw) {
  const threadId = raw.thread_id || raw.id || `${Date.now()}`;

  if (Array.isArray(raw.turns) && raw.turns.length > 0) {
    return {
      id: raw.id || threadId,
      thread_id: threadId,
      title: raw.title || trimTitle(raw.turns[0].query || "Untitled topic"),
      created_at: raw.created_at || new Date().toISOString(),
      updated_at: raw.updated_at || raw.created_at || new Date().toISOString(),
      turns: raw.turns.map((turn) => ({
        query: turn.query || "",
        answer: turn.answer || "",
        sources: Array.isArray(turn.sources) ? turn.sources : [],
        created_at: turn.created_at || new Date().toISOString(),
      })),
    };
  }

  // Backward compatibility for older saved format.
  return {
    id: raw.id || threadId,
    thread_id: threadId,
    title: raw.title || trimTitle(raw.query || "Untitled topic"),
    created_at: raw.created_at || new Date().toISOString(),
    updated_at: raw.updated_at || raw.created_at || new Date().toISOString(),
    turns: [
      {
        query: raw.query || raw.title || "",
        answer: raw.answer || "",
        sources: Array.isArray(raw.sources) ? raw.sources : [],
        created_at: raw.created_at || new Date().toISOString(),
      },
    ],
  };
}

function loadTopics() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      topics = [];
      return;
    }

    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) {
      topics = [];
      return;
    }

    topics = parsed.map(normalizeTopic).filter((topic) => topic.id && topic.thread_id);
  } catch {
    topics = [];
  }
}

function renderSources(sources) {
  sourcesEl.innerHTML = "";

  if (!sources.length) {
    const empty = document.createElement("li");
    empty.textContent = "No sources returned.";
    sourcesEl.appendChild(empty);
    return;
  }

  for (const source of sources) {
    const li = document.createElement("li");
    li.className = "source";

    const link = document.createElement("a");
    link.href = source.url;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = `[${source.id}] ${source.title}`;

    const snippet = document.createElement("p");
    snippet.textContent = source.snippet || "No snippet.";

    li.appendChild(link);
    li.appendChild(snippet);
    sourcesEl.appendChild(li);
  }
}

function getTopicById(topicId) {
  return topics.find((topic) => topic.id === topicId) || null;
}

function getActiveTopic() {
  return getTopicById(activeTopicId);
}

function renderActiveTopic() {
  const topic = getActiveTopic();

  if (!topic) {
    topicPill.textContent = "No topic selected";
    answerEl.textContent = "Run a query to see results.";
    renderSources([]);
    return;
  }

  topicPill.textContent = topic.title;

  const transcript = topic.turns
    .map((turn, idx) => `Q${idx + 1}: ${turn.query}\nA${idx + 1}: ${turn.answer}`)
    .join("\n\n");

  answerEl.textContent = transcript || "No answer returned.";

  const latestTurn = topic.turns[topic.turns.length - 1] || { sources: [] };
  renderSources(latestTurn.sources || []);
}

function selectTopic(topicId) {
  activeTopicId = topicId;
  renderHistory();
  renderActiveTopic();
}

function renderHistory() {
  historyListEl.innerHTML = "";

  if (!topics.length) {
    const empty = document.createElement("li");
    empty.textContent = "No saved topics yet.";
    historyListEl.appendChild(empty);
    return;
  }

  for (const topic of topics) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "history-item-btn" + (topic.id === activeTopicId ? " active" : "");

    const title = document.createElement("span");
    title.className = "history-title";
    title.textContent = topic.title;

    const timestamp = document.createElement("span");
    timestamp.className = "history-time";
    timestamp.textContent = formatTime(topic.updated_at || topic.created_at);

    button.appendChild(title);
    button.appendChild(timestamp);
    button.addEventListener("click", () => selectTopic(topic.id));

    item.appendChild(button);
    historyListEl.appendChild(item);
  }
}

function startNewTopic() {
  activeTopicId = null;
  renderHistory();
  renderActiveTopic();
  queryEl.focus();
  setStatus("Started a new topic. Ask your first question.");
}

function addOrUpdateTopic(query, data) {
  const now = new Date().toISOString();
  const active = getActiveTopic();

  const turn = {
    query,
    answer: data.answer || "",
    sources: Array.isArray(data.sources) ? data.sources : [],
    created_at: now,
  };

  if (active && data.thread_id === active.thread_id) {
    active.turns.push(turn);
    active.updated_at = now;
    saveTopics();
    selectTopic(active.id);
    return;
  }

  const topic = {
    id: data.thread_id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    thread_id: data.thread_id || `${Date.now()}`,
    title: trimTitle(query),
    created_at: now,
    updated_at: now,
    turns: [turn],
  };

  topics.unshift(topic);
  saveTopics();
  selectTopic(topic.id);
}

async function runResearch() {
  const query = queryEl.value.trim();
  if (!query) {
    setStatus("Enter a question first.");
    queryEl.focus();
    return;
  }

  runBtn.disabled = true;
  setStatus("Running research...");

  const payload = { query };
  const active = getActiveTopic();
  if (active && active.thread_id) {
    payload.thread_id = active.thread_id;
  }

  try {
    const response = await fetch("/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      const errorMessage = data?.detail || "Request failed.";
      throw new Error(errorMessage);
    }

    addOrUpdateTopic(query, data);
    queryEl.value = "";
    setStatus(`Done. ${data.meta?.source_count ?? 0} sources used.`);
  } catch (error) {
    setStatus(`Error: ${error.message}`);
  } finally {
    runBtn.disabled = false;
  }
}

function clearHistory() {
  topics = [];
  activeTopicId = null;
  saveTopics();
  renderHistory();
  renderActiveTopic();
  setStatus("History cleared.");
}

runBtn.addEventListener("click", runResearch);
clearHistoryBtn.addEventListener("click", clearHistory);
newTopicBtn.addEventListener("click", startNewTopic);

queryEl.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    runResearch();
  }
});

loadTopics();
if (topics.length > 0) {
  activeTopicId = topics[0].id;
}
renderHistory();
renderActiveTopic();
setStatus("Ready. Ask your question.");