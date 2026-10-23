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


def supporting_packet_text(packet: dict) -> str:
    """Keep checked supporting groups intact when sending them as model data."""
    if not isinstance(packet, dict) or packet.get('version') != 1 or not isinstance(packet.get('academicItems'), list):
        raise ValueError('Checked supporting packet is unavailable')
    serialized = source_bundle_text(packet)
    if len(serialized) > 90000:
        raise ValueError('Checked supporting packet exceeds the budget; select fewer sources or split the request')
    return serialized


SUPPORTING_PROVENANCE_POLICY = """
When CHECKED SUPPORTING EVIDENCE is supplied, ground academic content in selected
lecture originals and the packet's eligible academicItems. Do not promote
structuralPapers, qualifiedItems, upload names, topic labels, or analysis metadata
into academic facts. Historical papers can determine exam format only through
the supplied blueprint. If unknownQuestionCount is positive, obey totalQuestions
and the known question-type counts; do not infer a type for the unknown remainder.

For every academic output field, provide a provenance array of selectors. Each
selector has: path (JSON Pointer into the final output), optional quote (an exact
substring occurring exactly once in that field), authority (lecture,
supplementary, or reported_note), relation, sourceRefs, supportingSourceRefs,
supportingSourceProofs, and lectureAnchorRefs. Omit start/end: the backend
calculates offsets from final output. A selector without quote covers its entire
field. Cover every non-whitespace character; use multiple non-overlapping quotes
for mixed authority. For lecture claims use relation lecture_supported and only
sourceRefs. For supporting claims copy exact checked refs and proofs from an
eligible item and cite its selected lecture anchor. Use relation
related_supplementary unless the packet explicitly supports lecture_supported.
Never describe student notes as direct professor speech; write 'student notes
report ...' or equivalent in the attributed claim. Qualified unanchored items
are for tutor discussion only and must explicitly state the scope or conflict
qualification. Each section, term, card and question row's sourceRefs and
supportingSourceRefs must include the union of its claims. The summary root
covers overview and examFocus claims; the exam's shared refs cover only
sharedContext claims. Never invent evidence or copy citations by topic.

Paths: summary /overview, /sections/N/heading, /sections/N/content,
/sections/N/keyPoints/N, /keyTerms/N/term, /keyTerms/N/definition,
/examFocus/N. Flashcard each card has /front, /back, /topic. Tutor /reply.
Exam selectors live inside secret-rubrics JSON and cover /sharedContext for
academic TeX outside questions and /questions/qN/text for printed question
text, plus /questions/qN/correct_answer, /questions/qN/criteria, and
/questions/qN/explanation when present. Cite the question's complete
supportingSourceRefs and sourceRefs. Preserve the exact selected source identity.

For exams and flashcards, every tested academic premise, operation, method and
answer must follow from the selected lecture originals. A supporting proof plus
a related lecture anchor does not authorize extra knowledge. Supporting materials
may supply accurate attribution, emphasis, style and explicitly hypothetical
givens. Keep a question's grading answer/criteria consistent with its complete
wording, options and shared definitions; it will be checked jointly against all
cited question and shared lecture originals. Return only the documented schema
fields. Do not add explanation, example or other academic keys outside the
listed summary/card fields or the documented exam rubric explanation field.
"""


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
