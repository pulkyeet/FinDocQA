"""Web search and fallback for out-of-corpus questions (Plan §11).

Flow:
  1. RAG answers; if the LLM abstains ("Not found in corpus") AND
     the question is expected to come from the web:
  2. Search the web with duckduckgo-search
  3. Build a fresh prompt with web results
  4. Re-generate an answer tagged with "[source: web]"
"""

from ddgs import DDGS

ABSTAIN_PHRASES = [
    "not found in corpus",
    "cannot be found",
    "cannot find",
    "does not contain",
    "not available",
    "no information",
    "context does not",
    "not in the provided context",
    "i cannot find",
    "is not provided",
    "not mentioned",
]


def is_abstention(answer_text: str) -> bool:
    if not answer_text:
        return True
    t = answer_text.lower()
    return any(p in t for p in ABSTAIN_PHRASES)


def web_search(query: str, max_results: int = 3) -> list[dict]:
    try:
        with DDGS(timeout=15) as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return [
            {"title": r["title"], "snippet": r["body"], "url": r["href"]}
            for r in results
        ]
    except Exception:
        return []


def build_web_prompt(question: str) -> str:
    results = web_search(question)
    if not results:
        return (
            "Answer the question using your own knowledge. "
            "Tag your answer with '[source: web]'. "
            "If you do not know the answer, say 'Not found on web.'\n\n"
            f"Question: {question}\n\nAnswer:"
        )
    blocks = []
    for r in results:
        blocks.append(
            f"[source: {r['url']}]\nTitle: {r['title']}\n{r['snippet']}"
        )
    context = "\n\n-----\n\n".join(blocks)
    return (
        "Answer the question using ONLY the web search results below. "
        "This data comes from the web and may be less reliable than a "
        "corporate filing. Tag your answer with '[source: web]'. "
        "If the web results do not contain the answer, say 'Not found on web.'\n\n"
        f"Web Results:\n{context}\n\nQuestion: {question}\n\nAnswer:"
    )
