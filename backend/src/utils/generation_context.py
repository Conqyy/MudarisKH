"""Shared source-context formatting for independent study generators."""
import re
import json
from src.utils.text_normalization import as_text, text_list, budget_sources, source_texts


def source_bundle_text(bundle: dict) -> str:
    """Canonical data-only evidence formatting used by planner budget accounting.

    Callers place this in a user/data message and supply separate instructions.
    Formatting does not convert planned coverage into successful processing.
    """
    return json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _as_text(item) -> str:
    """Coerce an analysis item to a display string. Some documents store
    topics / formulas / workedExamples as dicts (e.g. {"title":..,"solution":..})
    instead of plain strings — handle both so ", ".join(...) never crashes."""
    return as_text(item)


def _join_texts(items, sep: str = ", ", limit: int | None = None) -> str:
    """Join a list of analysis items into a string, tolerating dict/non-string
    items (see _as_text). Replaces bare ", ".join(...) on raw analysis lists."""
    items = list(items or [])
    return sep.join(t for t in (_as_text(i) for i in items) if t)


def _course_topic_list(document_insights: list) -> list:
    """Legacy navigation labels for display; never authoritative source scope."""
    seen, out = set(), []
    for doc in document_insights or []:
        title = re.sub(r"^\s*\d+\s*[-.)]\s*", "", as_text(doc.get("documentTitle"))).strip()
        names = ([title] if title else []) + text_list(doc.get("topics", []))
        for t in names:
            t = as_text(t)
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out


def tutorial_brief(tutorial_insights: list = None, tutorial_texts: list = None,
                    max_problems: int = 10) -> str:
    """Compact text block describing tutorial practice problems (topics +
    problem ideas + methods) — shared by summary/flashcard generation."""
    parts = []
    for t in (tutorial_insights or []):
        topics_str = _join_texts(t.get("topics"), ", ", 15)
        block = f"Topics practiced: {topics_str}" if topics_str else ""
        lines = []
        for p in t.get("problems", []):
            concept = (p.get("concept") or "").strip()
            statement = (p.get("statement") or "").strip()
            method = (p.get("method") or "").strip()
            line = "• " + (f"{concept}: " if concept else "") + statement
            if method:
                line += f" (method: {method})"
            lines.append(line.strip())
        if lines:
            block += "\nPractice problems & how to solve them:\n" + "\n".join(lines)
        elif t.get("workedExamples"):
            block += "\nExercises: " + _join_texts(t.get("workedExamples"), ", ", 8)
        if block.strip():
            parts.append(block)
    if tutorial_texts:
        combined = source_texts(tutorial_texts, 8000)
        if combined.strip():
            parts.append("Raw tutorial problems:\n" + combined)
    return budget_sources([(f"analysis {i + 1}", part) for i, part in enumerate(parts)], 12000)[0]
