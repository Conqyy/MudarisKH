"""Deterministic, equally weighted evidence from individual historical papers.

Collection-level totals are never used when a papers array is present. Legacy
flat analyses remain uncertain single-paper evidence until their originals are
reanalyzed. This module makes no provider, storage, or database calls.
"""
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import math
from statistics import median
import unicodedata


_QUESTION_TYPES = frozenset({"mcq", "written", "true_false", "fill_blank", "matching",
    "equation", "proof", "calculation", "diagram", "code", "problem_solving", "essay"})


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return Fraction(0)
    return Fraction(str(value))


def _text(value):
    return unicodedata.normalize("NFKC", value).strip() if isinstance(value, str) else ""


def _stable(value):
    """Fingerprint content without depending on upload or evidence-list order."""
    if isinstance(value, dict): return {key: _stable(item) for key, item in sorted(value.items())}
    if isinstance(value, list): return sorted((_stable(item) for item in value), key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False))
    return value


def _fingerprint(value):
    encoded = json.dumps(_stable(value), ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def flatten_exam_papers(historical_analysis: list) -> list[dict]:
    """Return copied papers with stable source IDs and explicit legacy status.

    Accept raw analyses or stored records containing an ``analysis`` object.
    A papers array, including an empty one, always supersedes flat aggregates.
    """
    result = []
    for source in historical_analysis or []:
        if not isinstance(source, dict): continue
        analysis = source.get("analysis") if isinstance(source.get("analysis"), dict) else source
        source_id = next((_text(source.get(key)) or _text(analysis.get(key))
                          for key in ("sourceId", "_sourceId", "id", "documentId", "docId")
                          if _text(source.get(key)) or _text(analysis.get(key))), "") or _fingerprint(analysis)
        title = next((_text(source.get(key)) or _text(analysis.get(key))
                      for key in ("sourceTitle", "documentTitle", "title", "filename")
                      if _text(source.get(key)) or _text(analysis.get(key))), "")
        structured = isinstance(analysis.get("papers"), list)
        if analysis.get("analysisVersion") == 2 and not structured:
            continue
        papers = analysis["papers"] if structured else [analysis]
        for paper in papers:
            if not isinstance(paper, dict): continue
            item = deepcopy(paper)
            item["paperId"] = _text(paper.get("paperId")) or _text(paper.get("id")) or _fingerprint(paper)
            item["_sourceId"], item["_sourceTitle"], item["_legacy"] = source_id, title, not structured
            result.append(item)
    return sorted(result, key=lambda item: (item["_sourceId"], item["paperId"], _fingerprint(item)))


def _fractions(rows, label, value, allowed=None, canonicalize=_text):
    values = {}
    for row in rows or []:
        if not isinstance(row, dict): continue
        key = canonicalize(row.get(label))
        if not key or (allowed is not None and key not in allowed): continue
        amount = _number(row.get(value))
        values[key] = values.get(key, Fraction(0)) + amount
    total = sum(values.values())
    return {key: amount / total for key, amount in values.items() if amount} if total else {}


def _type_fractions(paper):
    rows = paper.get("questionTypes", [])
    return _fractions(rows, "type", "count", _QUESTION_TYPES) or _fractions(rows, "type", "percentage", _QUESTION_TYPES)


def _topic_label(value):
    return " ".join(_text(value).split())


def _topic_key(value):
    return _topic_label(value).casefold()


def _topic_rows(paper):
    return [row for row in paper.get("topicWeights", [])
            if isinstance(row, dict) and row.get("inScope") is not False
            and ('scopeStatus' not in row or (row.get('scopeStatus') == 'matched' and row.get('sourceRefs')))]


def _topic_display_labels(papers):
    labels = {}
    for paper in papers:
        for row in _topic_rows(paper):
            label = _topic_label(row.get("topic"))
            if label:
                key = label.casefold()
                # Choose from all eligible evidence, never the first upload.
                labels[key] = min(labels.get(key, label), label)
    return labels


def _topic_fractions(paper):
    # Scope constrains content, never the paper's structural evidence. Filter
    # before normalization so excluded topic weight cannot dilute kept topics.
    rows = _topic_rows(paper)
    return (_fractions(rows, "topic", "weight", canonicalize=_topic_key)
            or _fractions(rows, "topic", "questionCount", canonicalize=_topic_key))


def _paper_count(paper):
    count = _number(paper.get("totalQuestions"))
    if count and count.denominator == 1: return int(count)
    total = sum((_number(row.get("count")) for row in paper.get("questionTypes", []) if isinstance(row, dict)), Fraction(0))
    return int(total) if total and total.denominator == 1 else 0


def _average(distributions):
    distributions = [row for row in distributions if row]
    if not distributions: return {}
    keys = sorted(set().union(*distributions))
    return {key: sum((row.get(key, Fraction(0)) for row in distributions), Fraction(0)) / len(distributions) for key in keys}


def _allocation(weights, total):
    """Largest remainders with an alphabetical type/topic tie break."""
    if not weights: return {}
    scale = sum(weights.values())
    quotas = {key: value * total / scale for key, value in weights.items()}
    counts = {key: quota.numerator // quota.denominator for key, quota in quotas.items()}
    remaining = total - sum(counts.values())
    for key in sorted(quotas, key=lambda key: (-(quotas[key] - counts[key]), key))[:remaining]: counts[key] += 1
    return counts


def _exam_type(value):
    value = _text(value).casefold().replace(" ", "").replace("_", "").replace("-", "")
    return {"finalexam": "final", "midtermexam": "midterm", "quizexam": "quiz"}.get(value, value)


def _strings(papers, key):
    values = set()
    for paper in papers:
        value = paper.get(key, [])
        for item in value if isinstance(value, list) else [value]:
            text = _text(item)
            if text: values.add(text)
    return sorted(values)


def build_exam_blueprint(historical_analysis: list, total_marks: int | None = None,
                         exam_type: str = "Final") -> dict | None:
    """Build a typical paper, never the sum of a collection's question counts.

    Structure uses papers matching the requested type when available. Known
    original marks provide a robust median questions-per-mark ratio. Otherwise
    the median count is bounded by requested marks; a Quiz without matching
    evidence defaults to two marks per question (five questions without marks).
    Topics and difficulty retain equally weighted evidence from all papers.
    """
    if total_marks is not None and (type(total_marks) is not int or total_marks < 1):
        raise ValueError("Exam marks must be a positive integer")
    detected = flatten_exam_papers(historical_analysis)
    papers = [paper for paper in detected if _paper_count(paper) and _type_fractions(paper)]
    if not papers: return None
    requested = _exam_type(exam_type)
    matching = [paper for paper in papers if _exam_type(paper.get("examType")) == requested]
    cohort = matching or papers
    known = [paper for paper in cohort if _number(paper.get("totalMarks"))]
    if total_marks is not None and known:
        typical = median([Fraction(_paper_count(paper)) / _number(paper["totalMarks"]) for paper in known]) * total_marks
        count_method = "median_question_density"
    elif not matching and requested == "quiz":
        typical = Fraction(total_marks, 2) if total_marks is not None else Fraction(5)
        count_method = "quiz_marks_fallback"
    else:
        typical = median([Fraction(_paper_count(paper)) for paper in cohort])
        count_method = "median_question_count"
    count = max(1, (typical + Fraction(1, 2)).numerator // (typical + Fraction(1, 2)).denominator)
    if total_marks is not None: count = min(count, total_marks)
    types = _average([_type_fractions(paper) for paper in cohort])
    allocated = _allocation(types, count)
    topic_evidence = [_topic_fractions(paper) for paper in papers]
    topics = _average(topic_evidence)
    topic_labels = _topic_display_labels(papers)
    topic_counts = _allocation(topics, count)
    difficulty_evidence = [_fractions(paper.get("difficultyDistribution", []), "level", "percentage", {"easy", "medium", "hard"}) for paper in papers]
    difficulty = _average(difficulty_evidence)
    all_types = _average([_type_fractions(paper) for paper in papers])
    source_ids = sorted({paper["_sourceId"] for paper in papers})
    type_styles = {}
    all_type_styles = set()
    for paper in papers:
        for item in paper.get("questionTypes", []):
            if not isinstance(item, dict): continue
            style = _text(item.get("style"))
            if style:
                all_type_styles.add(style)
                if paper in cohort: type_styles.setdefault(item.get("type"), set()).add(style)
    question_types = []
    for kind in sorted(allocated):
        if not allocated[kind]: continue
        row = {"type": kind, "count": allocated[kind], "percentage": 100 * allocated[kind] / count}
        if kind in type_styles: row["style"] = "; ".join(sorted(type_styles[kind]))
        question_types.append(row)
    sources = [{"sourceId": paper["_sourceId"], "sourceTitle": paper["_sourceTitle"],
                "paperId": paper["paperId"], "examType": _text(paper.get("examType")) or "Unknown",
                "totalQuestions": _paper_count(paper), "totalMarks": float(_number(paper.get("totalMarks"))) or None,
                "legacyUncertain": paper["_legacy"], "usedForStructure": paper in cohort} for paper in papers]
    return {
        "blueprintVersion": 1, "examType": exam_type, "targetMarks": total_marks,
        "totalQuestions": count,
        "questionTypes": question_types,
        "topicWeights": [{"topic": topic_labels[topic], "weight": float(weight), "questionCount": topic_counts[topic]}
                         for topic, weight in sorted(topics.items())],
        "difficultyDistribution": [{"level": level, "percentage": float(value * 100)} for level, value in sorted(difficulty.items())],
        "patterns": _strings(papers, "patterns"),
        "styles": sorted(set(_strings(papers, "style") + _strings(papers, "styles")) | all_type_styles),
        "gradingBlueprint": "\n".join(_strings(papers, "gradingBlueprint")),
        "evidence": {
            "sourceCount": len(source_ids), "paperCount": len(papers),
            "detectedPaperCount": len(detected), "unusablePaperCount": len(detected) - len(papers),
            "topicEvidencePaperCount": sum(bool(row) for row in topic_evidence),
            "difficultyEvidencePaperCount": sum(bool(row) for row in difficulty_evidence),
            "unknownExamTypePaperCount": sum(_exam_type(paper.get("examType")) in ("", "unknown") for paper in papers),
            "structuredPaperCount": sum(not paper["_legacy"] for paper in papers),
            "legacyPaperCount": sum(paper["_legacy"] for paper in papers),
            "structurePaperCount": len(cohort), "knownMarksPaperCount": len(known),
            "structureCohort": "matching_exam_type" if matching else "all_papers_fallback",
            "structureFallback": not bool(matching), "countMethod": count_method,
            "typeDistribution": [{"type": kind, "percentage": float(value * 100)} for kind, value in sorted(all_types.items())],
            "sources": sources,
        },
    }
