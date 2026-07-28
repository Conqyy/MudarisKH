"""Course-scope topic matching.

Decides whether a past-exam topic is still covered by the course's CURRENT
lecture documents. Used by the Historical Exam Analyzer to tag each past-exam
topic as in/out of the current course (so removed topics don't drive exam
generation). Pure string heuristics — no LLM call.
"""
import re

# Generic words that shouldn't decide whether a topic is "in the course".
_SCOPE_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "using", "use",
    "based", "introduction", "overview", "concepts", "concept", "fundamentals",
    "basics", "topic", "topics", "chapter", "section", "part", "general",
    "review", "advanced", "basic", "methods", "method", "analysis", "design",
    "system", "systems", "problem", "problems",
}


def core_words(text: str) -> set:
    """Meaningful lowercase words (drops generic/stop words)."""
    return {
        w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(w) > 2 and w not in _SCOPE_STOPWORDS
    }


def variants(w: str) -> set:
    """A word plus its singular form, so plural/singular phrasing differences
    (e.g. "trees" vs "tree") still match."""
    v = {w}
    if w.endswith("ies") and len(w) > 4:
        v.add(w[:-3] + "y")
    elif w.endswith("es") and len(w) > 4:
        v.add(w[:-2])
    if w.endswith("s") and len(w) > 3:
        v.add(w[:-1])
    return v


def scope_words(text: str) -> set:
    """Expanded word set (with singular variants) used to build course scope."""
    out = set()
    for w in core_words(text):
        out |= variants(w)
    return out


def course_scope_from_docs(document_insights: list) -> tuple:
    """Build (display_topics, scope_word_set) from the current lecture documents.
    These define the course as taught NOW — the authoritative topic whitelist."""
    display, words = [], set()
    for doc in document_insights or []:
        # The document title is often the clearest topic name (e.g. a chapter
        # titled "13- NP-Completeness") — include it in the scope.
        title = (doc.get("documentTitle") or "").strip()
        if title:
            # Drop a leading "5-" / "13- " numbering prefix from the display name.
            clean = re.sub(r"^\s*\d+\s*[-.)]\s*", "", title).strip()
            if clean:
                display.append(clean)
            words |= scope_words(title)
        for t in (doc.get("topics", []) or []):
            t = (t or "").strip()
            if t:
                display.append(t)
                words |= scope_words(t)
        for d in (doc.get("definitions", []) or [])[:25]:
            if isinstance(d, dict) and d.get("term"):
                words |= scope_words(d["term"])
        for dg in (doc.get("diagrams", []) or [])[:15]:
            if isinstance(dg, dict) and dg.get("name"):
                words |= scope_words(dg["name"])
    # De-dup display list while preserving order.
    seen, uniq = set(), []
    for t in display:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    return uniq, words


def retag_topic_weights(historical_analyses: list, document_insights: list) -> list:
    """Re-decide each past-exam topic's ``inScope`` flag against the documents
    the student SELECTED for this generation (not the whole course).

    The Historical Exam Analyzer tags ``inScope`` once at upload time, against
    every document in the course — so picking only "Chapter 1" would still leave
    every other chapter's topics flagged in-scope and the past exam would drag
    the whole course back into the output. Re-tagging here makes the selection
    the scope: topics outside the selected documents come back ``inScope=False``,
    which the generators already know how to drop and renormalize around.

    Returns shallow copies (the stored analyses are never mutated). When no
    documents were selected there is nothing to scope against, so the analyses
    are returned unchanged and the caller falls back to previous behavior."""
    _, words = course_scope_from_docs(document_insights)
    if not words:
        return historical_analyses or []

    out = []
    for h in historical_analyses or []:
        h2 = dict(h or {})
        weights = []
        for w in (h2.get("topicWeights") or []):
            w2 = dict(w or {})
            w2["inScope"] = topic_in_scope(w2.get("topic", ""), words)
            weights.append(w2)
        h2["topicWeights"] = weights
        out.append(h2)
    return out


def topic_in_scope(topic: str, words: set) -> bool:
    """A past-exam topic is in scope only if MOST of its distinctive words are
    covered by the current course documents — not just one shared word. This
    distinguishes e.g. "Linear Programming" (only the generic "programming"
    overlaps a course that teaches "Dynamic Programming") from a genuine match.
    Topics with no extractable words are treated as in scope (can't judge)."""
    core = core_words(topic)
    if not core:
        return True
    matched = sum(1 for w in core if variants(w) & words)
    return matched / len(core) > 0.5
