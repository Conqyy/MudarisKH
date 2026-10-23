"""Authoritative historical categories and deterministic collection routing.

Categories are metadata supplied by the owner, never inferred from source text.
The four-key supporting identity and its hashes deliberately remain unchanged.
"""
import uuid

HISTORICAL_EXAM_COLLECTIONS = {
    'quiz': 'historical_quizzes',
    'midterm': 'historical_midterms',
    'final': 'historical_finals',
}
LEGACY_HISTORICAL_EXAMS = 'historical_exams'
HISTORICAL_EXAM_LOCATIONS = 'historical_exam_locations'
ALL_HISTORICAL_EXAM_COLLECTIONS = (LEGACY_HISTORICAL_EXAMS, *HISTORICAL_EXAM_COLLECTIONS.values())


def normalize_historical_exam_type(value, allow_none=False):
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or value not in HISTORICAL_EXAM_COLLECTIONS:
        raise ValueError('Historical exam type must be quiz, midterm, or final')
    return value


def historical_exam_collection(exam_type):
    return HISTORICAL_EXAM_COLLECTIONS[normalize_historical_exam_type(exam_type)]


def historical_exam_type_from_id(exam_id):
    if isinstance(exam_id, str):
        for kind, collection in HISTORICAL_EXAM_COLLECTIONS.items():
            if exam_id.startswith(collection + '_'):
                return kind
    return None


def new_historical_exam_id(exam_type):
    return historical_exam_collection(exam_type) + '_' + uuid.uuid4().hex
