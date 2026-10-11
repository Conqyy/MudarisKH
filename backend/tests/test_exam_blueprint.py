from copy import deepcopy

import pytest

from src.utils.exam_blueprint import build_exam_blueprint, flatten_exam_papers


def paper(identifier, count=20, marks=40, kind="Final", topic="Limits", types=None):
    return {
        "paperId": identifier, "examType": kind, "totalQuestions": count, "totalMarks": marks,
        "questionTypes": types or [{"type": "mcq", "count": count}],
        "topicWeights": [{"topic": topic, "weight": 1, "questionCount": count}],
        "difficultyDistribution": [{"level": "medium", "percentage": 100}],
        "patterns": ["Explain reasoning"], "gradingBlueprint": "Partial credit for working",
    }


def source(identifier, papers):
    return {"sourceId": identifier, "analysisVersion": 2, "papers": papers}


def test_upload_and_paper_order_do_not_change_blueprint():
    rows = [source("B", [paper("b2", topic="Derivatives"), paper("b1")]),
            source("A", [paper("a", count=10, marks=20)])]
    assert build_exam_blueprint(rows, 20) == build_exam_blueprint([
        source("A", [paper("a", count=10, marks=20)]),
        source("B", list(reversed(rows[0]["papers"]))),
    ], 20)


def test_ten_papers_in_one_file_are_not_one_two_hundred_question_exam():
    result = build_exam_blueprint([source("collection", [paper(str(i)) for i in range(10)])])
    assert result["totalQuestions"] == 20
    assert result["evidence"]["sourceCount"] == 1
    assert result["evidence"]["paperCount"] == 10


def test_topics_are_equal_per_paper_not_per_upload_or_question_count():
    result = build_exam_blueprint([source("long", [paper("a", count=100, marks=200)]),
                                   source("short", [paper("b", count=5, marks=10, topic="Derivatives")])])
    assert {row["topic"]: row["weight"] for row in result["topicWeights"]} == {"Limits": .5, "Derivatives": .5}


def test_normalizes_each_paper_before_averaging():
    a, b = paper("a"), paper("b")
    a["topicWeights"] = [{"topic": "A", "weight": 8}, {"topic": "B", "weight": 2}]
    b["topicWeights"] = [{"topic": "A", "weight": .2}, {"topic": "B", "weight": .8}]
    result = build_exam_blueprint([source("s", [a, b])])
    assert {row["topic"]: row["weight"] for row in result["topicWeights"]} == {"A": .5, "B": .5}


def test_matching_exam_type_controls_structure_but_all_topics_contribute():
    final = paper("final", count=40, marks=80, topic="Derivatives")
    quiz = paper("quiz", count=4, marks=10, kind="Quiz", types=[{"type": "written", "count": 4}])
    result = build_exam_blueprint([source("s", [final, quiz])], 10, "Quiz")
    assert result["totalQuestions"] == 4
    assert result["questionTypes"] == [{"type": "written", "count": 4, "percentage": 100.0}]
    assert len(result["topicWeights"]) == 2
    assert result["evidence"]["structureCohort"] == "matching_exam_type"


def test_known_marks_scale_typical_density_and_unknown_marks_bound_count():
    result = build_exam_blueprint([source("s", [paper("a", count=40, marks=80)])], 10, "Quiz")
    assert result["totalQuestions"] == 5
    assert result["evidence"]["countMethod"] == "median_question_density"
    unknown = build_exam_blueprint([source("s", [paper("a", count=40, marks=None)])], 7)
    assert unknown["totalQuestions"] == 7


def test_missing_quiz_cohort_and_marks_does_not_copy_huge_final_count():
    result = build_exam_blueprint([source("s", [paper("a", count=100, marks=None)])], 10, "Quiz")
    assert result["totalQuestions"] == 5
    assert result["evidence"]["structureFallback"] is True


def test_type_allocation_averages_fractions_and_uses_deterministic_ties():
    a = paper("a", count=100, types=[{"type": "written", "count": 100}])
    b = paper("b", count=2, types=[{"type": "mcq", "count": 2}])
    result = build_exam_blueprint([source("s", [a, b])], 3)
    counts = {row["type"]: row["count"] for row in result["questionTypes"]}
    assert counts == {"mcq": 2, "written": 1}
    assert sum(counts.values()) == result["totalQuestions"] == 3


def test_count_uses_robust_median_instead_of_outlier_mean():
    result = build_exam_blueprint([source("s", [paper(str(i), count=n, marks=None) for i,n in enumerate([10, 12, 100])])])
    assert result["totalQuestions"] == 12


def test_provenance_patterns_styles_and_legacy_uncertainty_are_preserved():
    legacy = paper("old", count=8)
    legacy["sourceId"] = "legacy"
    new = paper("new")
    new["style"] = "Show calculations"
    new["patterns"] = ["Use diagrams"]
    rows = [legacy, source("new-source", [new])]
    previous = deepcopy(rows)
    result = build_exam_blueprint(rows)
    assert rows == previous
    assert result["evidence"]["legacyPaperCount"] == 1
    assert result["evidence"]["structuredPaperCount"] == 1
    assert result["patterns"] == ["Explain reasoning", "Use diagrams"]
    assert "Show calculations" in result["styles"]
    assert {row["sourceId"] for row in result["evidence"]["sources"]} == {"legacy", "new-source"}
    assert len(flatten_exam_papers(rows)) == 2


def test_empty_analysis_returns_none_and_invalid_marks_fail():
    assert build_exam_blueprint([]) is None
    for marks in (0, -1, True, 2.5):
        with pytest.raises(ValueError): build_exam_blueprint([], marks)


def test_version_two_empty_collection_never_falls_back_to_aggregate_counts():
    row = source("empty", [])
    row.update(totalQuestions=500, questionTypes=[{"type": "mcq", "count": 500}])
    assert build_exam_blueprint([row]) is None


def test_preserves_per_question_type_styles_from_every_paper():
    a, b = paper("a"), paper("b")
    a["questionTypes"][0]["style"] = "Trace a program"
    b["questionTypes"][0]["style"] = "Select the output"
    result = build_exam_blueprint([source("s", [a, b])])
    assert result["questionTypes"][0]["style"] == "Select the output; Trace a program"
    assert result["styles"] == ["Select the output", "Trace a program"]


def test_stable_provenance_without_explicit_source_or_paper_ids():
    rows = [source("x", [paper("a"), paper("b", topic="Derivatives")]), source("y", [paper("c")])]
    for row in rows:
        del row["sourceId"]
        for item in row["papers"]: del item["paperId"]
    reverse = deepcopy(list(reversed(rows)))
    reverse[-1]["papers"].reverse()
    assert build_exam_blueprint(rows) == build_exam_blueprint(reverse)


def test_difficulty_averages_every_paper_and_discloses_missing_evidence():
    a, b = paper("a"), paper("b", kind="Quiz")
    a["difficultyDistribution"] = [{"level": "hard", "percentage": 100}]
    b["difficultyDistribution"] = [{"level": "easy", "percentage": 100}]
    c = paper("c")
    c["difficultyDistribution"] = []
    result = build_exam_blueprint([source("s", [a, b, c])])
    assert result["difficultyDistribution"] == [{"level": "easy", "percentage": 50.0}, {"level": "hard", "percentage": 50.0}]
    assert result["evidence"]["difficultyEvidencePaperCount"] == 2


def test_excluded_topics_are_removed_before_normalization_without_losing_other_evidence():
    a, b = paper("a"), paper("b", types=[{"type": "written", "count": 20}])
    a["topicWeights"] = [
        {"topic": "Limits", "weight": .1, "inScope": True},
        {"topic": "Excluded", "weight": .9, "inScope": False},
    ]
    b["topicWeights"] = [{"topic": "Derivatives", "weight": 1, "inScope": None}]
    a["difficultyDistribution"] = [{"level": "hard", "percentage": 100}]
    b["difficultyDistribution"] = [{"level": "easy", "percentage": 100}]

    result = build_exam_blueprint([source("s", [a, b])])

    assert {row["topic"]: row["weight"] for row in result["topicWeights"]} == {"Limits": .5, "Derivatives": .5}
    assert {row["type"]: row["count"] for row in result["questionTypes"]} == {"mcq": 10, "written": 10}
    assert result["difficultyDistribution"] == [{"level": "easy", "percentage": 50.0}, {"level": "hard", "percentage": 50.0}]


def test_paper_with_all_topics_excluded_still_contributes_structure_and_difficulty():
    a, b = paper("a"), paper("b", types=[{"type": "written", "count": 20}])
    a["topicWeights"] = [{"topic": "Excluded", "questionCount": 20, "inScope": False}]
    result = build_exam_blueprint([source("s", [a, b])])
    assert [row["topic"] for row in result["topicWeights"]] == ["Limits"]
    assert {row["type"]: row["count"] for row in result["questionTypes"]} == {"mcq": 10, "written": 10}
    assert result["evidence"]["topicEvidencePaperCount"] == 1
    assert result["evidence"]["difficultyEvidencePaperCount"] == 2


def test_recurring_topics_group_case_unicode_and_whitespace_before_weighting():
    a, b, c = [paper(identifier, count=3, marks=None) for identifier in ("a", "b", "c")]
    a["topicWeights"] = [
        {"topic": "Decision   Trees", "weight": .4},
        {"topic": " decision\u3000trees ", "weight": .6},
        {"topic": "Excluded", "weight": 9, "inScope": False},
    ]
    b["topicWeights"] = [{"topic": "\uff44\uff45\uff43\uff49\uff53\uff49\uff4f\uff4e trees", "weight": 1}]
    c["topicWeights"] = [{"topic": "Graphs", "weight": 1}]
    rows = [source("s", [a, b, c])]

    result = build_exam_blueprint(rows, 3)
    weights = {row["topic"]: row for row in result["topicWeights"]}

    assert set(weights) == {"Decision Trees", "Graphs"}
    assert weights["Decision Trees"]["weight"] == pytest.approx(2 / 3)
    assert weights["Graphs"]["weight"] == pytest.approx(1 / 3)
    assert weights["Decision Trees"]["questionCount"] == 2
    assert weights["Graphs"]["questionCount"] == 1
    reversed_rows = deepcopy(rows)
    reversed_rows[0]["papers"].reverse()
    reversed_rows[0]["papers"][-1]["topicWeights"].reverse()
    assert build_exam_blueprint(reversed_rows, 3) == result
