"""Knowledge-base search over ``data/kb.json`` (offline keyword retrieval)."""
from __future__ import annotations

import json
import os
import re
from typing import Any, Callable

from pydantic import BaseModel

from src.config import settings


class Article(BaseModel):
    id: str
    title: str
    category: str
    content: str
    tags: list[str] = []


class KBHit(BaseModel):
    id: str
    title: str
    category: str
    snippet: str
    score: float


_KB_PATH_OVERRIDE: str | None = None
_CACHE: dict[str, list[Article]] = {}

_STOPWORDS = frozenset(
    "a an the and or is are was were be been to of in on for with as at by from "
    "it its this that these those i me my we you your he she they them do does did "
    "how what when where which who why can could should would will just very really "
    "hi hello hey please thanks thank there here have has had not no yes if then than "
    "so but also about into over after".split()
)


def set_kb_path(path: str | None) -> None:
    """Override the KB json path (tests). Pass None to restore settings."""
    global _KB_PATH_OVERRIDE
    _KB_PATH_OVERRIDE = path


def resolve_kb_path() -> str:
    return _KB_PATH_OVERRIDE or settings.kb_path


def _load_articles() -> list[Article]:
    path = resolve_kb_path()
    if path not in _CACHE:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
        items = raw.get("articles", raw if isinstance(raw, list) else [])
        _CACHE[path] = [Article(**a) for a in items]
    return _CACHE[path]


def clear_cache() -> None:
    _CACHE.clear()


def _tokenize(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOPWORDS}


def _score(query_tokens: set[str], article: Article) -> float:
    if not query_tokens:
        return 0.0
    title_tokens = _tokenize(article.title)
    tag_tokens = {t.lower() for tag in article.tags for t in re.findall(r"[a-z0-9]+", tag)}
    body_tokens = _tokenize(article.content)
    title_hits = len(query_tokens & title_tokens)
    tag_hits = len(query_tokens & tag_tokens)
    body_hits = len(query_tokens & body_tokens)
    return 3.0 * title_hits + 2.0 * tag_hits + 1.0 * body_hits


def search_kb(query: str, top_k: int = 3) -> list[KBHit]:
    """Return up to ``top_k`` articles ranked by keyword overlap (empty if none)."""
    tokens = _tokenize(query or "")
    if not tokens:
        return []
    scored: list[tuple[float, Article]] = []
    for article in _load_articles():
        score = _score(tokens, article)
        if score > 0:
            scored.append((score, article))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    hits: list[KBHit] = []
    for score, article in scored[: max(top_k, 1)]:
        snippet = article.content[:220] + ("…" if len(article.content) > 220 else "")
        hits.append(KBHit(id=article.id, title=article.title, category=article.category, snippet=snippet, score=score))
    return hits


def get_article(article_id: str) -> Article | None:
    """Fetch a single article by id."""
    for article in _load_articles():
        if article.id == article_id:
            return article
    return None


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "kb_search",
            "description": "Search the support knowledge base for help articles matching the customer question.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Customer question or keywords"},
                    "top_k": {"type": "integer", "default": 3, "minimum": 1, "maximum": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "kb_get_article",
            "description": "Fetch the full text of a knowledge-base article by id.",
            "parameters": {
                "type": "object",
                "properties": {"article_id": {"type": "string"}},
                "required": ["article_id"],
            },
        },
    },
]


def _get_article_json(article_id: str) -> dict[str, Any]:
    article = get_article(article_id)
    return article.model_dump() if article else {"found": False, "article_id": article_id}


FUNCTIONS: dict[str, Callable[..., Any]] = {
    "kb_search": lambda query, top_k=3: {"hits": [h.model_dump() for h in search_kb(query, top_k)]},
    "kb_get_article": _get_article_json,
}
