"""Course-scope topic matching.

Decides whether a past-exam topic is still covered by the course's CURRENT
lecture documents. Used by the Historical Exam Analyzer to tag each past-exam
topic as in/out of the current course (so removed topics don't drive exam
generation). Pure string heuristics — no LLM call.
"""
import re
import unicodedata
from src.utils.text_normalization import as_text, text_list

# Generic words that shouldn't decide whether a topic is "in the course".
_SCOPE_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "using", "use",
    "based", "introduction", "overview", "concepts", "concept", "fundamentals",
    "basics", "topic", "topics", "chapter", "section", "part", "general",
    "review", "advanced", "basic", "methods", "method", "analysis", "design",
    "system", "systems", "problem", "problems",
    "of", "in", "to", "is", "it", "an", "at", "on", "by", "as", "or",
    "في", "من", "عن", "الى", "على", "هذا", "هذه", "هو", "هي", "و", "ال",
}


def core_words(text: str) -> set:
    """Meaningful lowercase words (drops generic/stop words)."""
    text = unicodedata.normalize('NFKC', as_text(text)).casefold()
    text = ''.join(c for c in text if not unicodedata.combining(c) and c != '\u0640')
    text = text.translate(str.maketrans({'أ': 'ا', 'إ': 'ا', 'آ': 'ا'}))
    return {
        w for w in re.findall(r"[^\W_]+", text, re.UNICODE)
        if len(w) > 1 and w not in _SCOPE_STOPWORDS
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
        if not isinstance(doc, dict):
            continue
        title = as_text(doc.get("documentTitle"))
        if title:
            # Drop a leading "5-" / "13- " numbering prefix from the display name.
            clean = re.sub(r"^\s*\d+\s*[-.)]\s*", "", title).strip()
            if clean:
                display.append(clean)
            words |= scope_words(title)
        for t in text_list(doc.get("topics", [])):
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
    # A selected document with unrecognizable metadata is still a scope
    # boundary, rather than permission to admit every historical topic.
    if document_insights and not words:
        words.add('__unrecognized_scope__')
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
    scope flags are cleared so historical-only generation remains usable."""
    _, words = course_scope_from_docs(document_insights)
    out = []
    for h in historical_analyses or []:
        h2 = dict(h or {})
        weights = []
        for w in (h2.get("topicWeights") or []):
            w2 = dict(w or {})
            w2["inScope"] = topic_in_scope(w2.get("topic", ""), words) if words else None
            weights.append(w2)
        h2["topicWeights"] = weights
        h2['scopeChecked'] = bool(words)
        h2['scopeStatus'] = 'document_scope' if words else 'no_doc_scope'
        h2['outOfCourseTopics'] = [as_text(w.get('topic')) for w in weights if w['inScope'] is False]
        out.append(h2)
    return out


def topic_in_scope(topic: str, words: set) -> bool:
    """A past-exam topic is in scope only if MOST of its distinctive words are
    covered by the current course documents — not just one shared word. This
    distinguishes e.g. "Linear Programming" (only the generic "programming"
    overlaps a course that teaches "Dynamic Programming") from a genuine match.
    Topics with no recognizable text fail closed when a scope exists."""
    core = core_words(topic)
    if not core:
        return not bool(words)
    matched = sum(1 for w in core if variants(w) & words)
    return matched / len(core) > 0.5
