"""Opt-in real lecture-foundation fixtures for unrelated API regressions."""
from copy import deepcopy

from src.utils.course_foundation import build_foundation_status


def lecture_document(identity='doc', topic='Limits', **overrides):
    analysis = {'topics': [topic], 'definitions': [], 'formulas': [],
                'chapterMapping': [], 'keyConceptCount': 1}
    return {'id': identity, 'userId': 'owner', 'courseId': 'course',
            'title': topic, 'status': 'completed', 'analysis': analysis,
            'extractedText': f'Lecture material about {topic}.', 'processedAt': 1000,
            **deepcopy(overrides)}


def confirm_lecture_foundation(db, documents=None, *, course_id='course', owner='owner'):
    """Populate real prerequisites; leave API ownership/readiness guards intact."""
    course = db.get_owned_course.return_value
    course = dict(course) if isinstance(course, dict) else {}
    course.update({'id': course_id, 'userId': owner})
    course.setdefault('title', 'Course')
    if documents is None:
        documents = [lecture_document(courseId=course_id, userId=owner)]
    owned_documents = [row for row in documents
                       if row.get('userId') == owner and row.get('courseId') == course_id]
    foundation = build_foundation_status(owned_documents)
    assert foundation['state'] == 'confirmation_required', 'Fixture must provide complete usable lecture documents'
    db.get_document_foundation.return_value = {'userId': owner, 'courseId': course_id,
                                             'revision': foundation['revision']}
    db.get_owned_course.return_value = course
    db._flat_get.return_value = course
    db.get_course_documents.return_value = documents
    return owned_documents
