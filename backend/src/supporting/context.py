"""Compile owned, scope-checked supporting evidence for generation."""
from copy import deepcopy
import re
import unicodedata

from src.supporting.alignment_evidence import context_components
from src.supporting.contracts import digest, validate_identity
from src.utils.storage_paths import validate_component


_SELECTION_KINDS = {'historical_ids': 'historical_exam', 'audio_ids': 'audio',
                    'tutorial_ids': 'tutorial'}
_PURPOSES = frozenset(('summary', 'exam', 'flashcards', 'tutor'))


def _complete(report):
    return (report.get('extractionCoverage', {}).get('complete') is True
            and report.get('alignmentCoverage', {}).get('complete') is True)


def _identity(row, category, user_id, course_id):
    kind = 'notes' if category == 'audio' and row.get('sourceType') == 'notes' else category
    return validate_identity({'userId': user_id, 'courseId': course_id,
                              'kind': kind, 'materialId': row['id']})


def _qualified_request(query):
    if not query or not query.strip(): return False
    english = (re.search(r'\b(discuss|explain|compare|show|why|what|analy[sz]e)\b', query, re.I)
               and re.search(r'\b(conflict|contradict|outside|out.of.scope|unsupported|uncertain|unverified)\b', query, re.I))
    arabic = (any(word in query for word in ('ناقش', 'اشرح', 'قارن', 'حلل', 'وضح'))
              and any(word in query for word in ('تعارض', 'تناقض', 'خارج', 'غير مؤكد', 'غير موثق')))
    return bool(english or arabic)


def _scope_snapshot(scope):
    return {'version': 1, 'scopeRevision': scope['scopeRevision'],
            'foundationRevision': scope.get('foundationRevision'),
            'documents': [{key: deepcopy(document.get(key)) for key in
                           ('id', 'title', 'sourceRevision', 'guideRevision')}
                          for document in scope.get('documents', [])],
            'allowedRefs': deepcopy(scope.get('allowedRefs', []))}


def _structural_paper(original):
    paper = {key: deepcopy(original.get(key)) for key in
             ('paperId', 'examType', 'totalQuestions', 'totalMarks', 'questionIds',
              'unknownQuestionTypeIds')}
    paper['questionTypes'] = [
        {key: deepcopy(row[key]) for key in ('type', 'count', 'percentage', 'questionIds') if key in row}
        for row in original.get('questionTypes', []) if isinstance(row, dict)]
    return paper


def _context_for(item, alignment, components):
    expected = {component['id']: component for component in components}
    deps = alignment.get('contextDependencies', [])
    if {dep.get('componentId') for dep in deps} != set(expected) or len(deps) != len(expected):
        raise ValueError('Original item context dependencies are missing or invented')
    context = []
    for dep in deps:
        component = expected[dep['componentId']]
        if any(dep.get(key) != component[key] for key in ('ownerType', 'ownerId', 'field', 'index', 'contentDigest')):
            raise ValueError('Original item context identity changed')
        if dep['decision'] == 'not_required':
            if not dep.get('verification'): raise ValueError('Context omission lacks independent verification')
            continue
        if dep['decision'] != 'required' or not dep.get('usable') or not dep.get('verification'):
            return None
        if dep['relation'] == 'source_only' and not (
                dep.get('contentKind') in ('hypothetical_data', 'procedural_instruction')
                and dep.get('methodRequired') is False):
            return None
        if dep['relation'] not in ('lecture_supported', 'source_only'):
            return None
        context.append({'componentId': dep['componentId'], 'ownerType': dep['ownerType'],
                        'ownerId': dep['ownerId'], 'field': dep['field'], 'index': dep['index'],
                        'value': deepcopy(component['value']), 'contentKind': dep['contentKind'],
                        'relation': dep['relation'], 'methodRequired': dep['methodRequired'],
                        'verification': deepcopy(dep['verification']),
                        'supportingSourceProofs': deepcopy(dep['supportingSourceProofs']),
                        'lectureSupportProofs': deepcopy(dep['lectureSupportProofs'])})
    return context


def _academic_item(item, alignment, context, identity, purpose):
    relations = {finding['relation'] for finding in alignment['requirements']}
    if not alignment['requirements'] or item['itemType'] in ('nonacademic', 'topic_statement'):
        return None
    supplementary = (identity['kind'] != 'historical_exam' and purpose in ('summary', 'tutor')
                     and item['itemType'] in ('teaching_point', 'example', 'emphasis')
                     and relations == {'related_supplementary'}
                     and all(finding['lectureAnchorRefs'] and finding['supportingSourceProofs']
                             for finding in alignment['requirements']))
    supported = relations == {'lecture_supported'} and alignment['status'] == 'covered'
    if not (supported or supplementary) or context is None:
        return None
    result = {key: deepcopy(item.get(key)) for key in ('id', 'parentId', 'paperId', 'printedLabel',
        'itemType', 'text', 'choices', 'givenData', 'printedMarks', 'requirements',
        'supportingSourceRefs', 'supportingSourceProofs')}
    result.update(materialIdentity=deepcopy(identity), sourceType='notes' if identity['kind'] == 'notes' else identity['kind'],
                  relation='related_supplementary' if supplementary else 'lecture_supported',
                  attribution='student-reported notes' if identity['kind'] == 'notes' else identity['kind'],
                  requiredContext=context, alignment=deepcopy(alignment))
    return result


class SupportingContextCompiler:
    def __init__(self, repository, library, aligner):
        self.repository = repository
        self.library = library
        self.aligner = aligner

    def compile(self, *, user_id, course_id, scope, selected, purpose, discussion_query=None):
        validate_component(user_id, 'user ID')
        validate_component(course_id, 'course ID')
        if not isinstance(scope, dict) or not isinstance(scope.get('scopeRevision'), str):
            raise ValueError('Selected lecture scope is required')
        if not isinstance(selected, dict) or set(selected) != set(_SELECTION_KINDS):
            raise ValueError('Supporting selections need historical_ids, audio_ids and tutorial_ids')
        if purpose not in _PURPOSES or discussion_query is not None and not isinstance(discussion_query, str):
            raise ValueError('Invalid supporting purpose or discussion query')
        for value in selected.values():
            if value is not None:
                if not isinstance(value, list): raise ValueError('Supporting selection must be a list or None')
                for identifier in value: validate_component(identifier, 'source ID')
        db = self.repository.database
        readers = {'historical_ids': db.get_course_historical_exams,
                   'audio_ids': db.get_course_audio_recordings,
                   'tutorial_ids': db.get_course_tutorials}
        identities = []
        for key, category in _SELECTION_KINDS.items():
            requested = selected[key]
            if requested == []: continue
            owned = [row for row in readers[key](course_id, user_id=user_id)
                     if row.get('userId') == user_id and row.get('courseId') == course_id]
            by_id = {row['id']: row for row in owned}
            if requested is None:
                chosen = sorted(owned, key=lambda row: row['id'])
            else:
                ids = list(dict.fromkeys(requested))
                if any(identifier not in by_id for identifier in ids):
                    raise ValueError('Selected supporting material is unavailable')
                chosen = [by_id[identifier] for identifier in ids]
            identities.extend(_identity(row, category, user_id, course_id) for row in chosen)
        prepared = []
        for identity in identities:
            row = self.repository.get_owned(identity)
            analysis, job = row.get('supportingAnalysis') or {}, row.get('processingJob') or {}
            expected = {key: analysis.get(key) for key in ('sourceRevision', 'reportRevision', 'analysisId')}
            ready = (row.get('status') == analysis.get('state') == job.get('stage') == 'completed'
                     and analysis.get('version') == 1 and all(expected.values())
                     and analysis['analysisId'] == job.get('id')
                     and row.get('originalDigest') and row['originalDigest'] == job.get('sourceDigest')
                     and (not scope.get('foundationRevision') or job.get('foundationRevision') == scope['foundationRevision'])
                     and not row.get('stale'))
            if not ready: raise ValueError('Selected supporting material is not ready; upgrade or deselect it')
            manifest = self.library.load_source(identity, expected['sourceRevision'])
            if manifest['sourceRevision'] != expected['sourceRevision'] or manifest['identity'] != identity or not manifest['coverage']['complete']:
                raise ValueError('Selected supporting source is incomplete or changed')
            baseline = self.library.load_report(identity, expected['reportRevision'])
            if baseline['sourceRevision'] != expected['sourceRevision'] or not _complete(baseline):
                raise ValueError('Selected supporting report is incomplete or changed')
            prepared.append((identity, expected, job, baseline))
        snapshot, academic, qualified, papers, exclusions = [], [], [], [], []
        for identity, expected, job, baseline in prepared:
            scoped_revision = expected['reportRevision']
            report = baseline
            if baseline['scopeSnapshot']['scopeRevision'] != scope['scopeRevision']:
                foundation = scope.get('foundationRevision') or job['foundationRevision']
                cached = (self.repository.get_scoped_cache(identity, expected, foundation_revision=foundation,
                    scope_revision=scope['scopeRevision'], alignment_version=baseline['alignmentVersion'])
                    if hasattr(self.repository, 'get_scoped_cache') else None)
                if cached:
                    scoped_revision = cached
                    report = self.library.load_report(identity, scoped_revision)
                else:
                    if self.aligner is None: raise ValueError('Scoped supporting alignment is unavailable')
                    report = self.aligner.rescope(identity, baseline, scope=scope, checkpoint=lambda state: None)
                    if not _complete(report): raise ValueError('Selected supporting rescope is incomplete')
                    adopted = self.library.save_scoped_report(identity, expected, report)
                    scoped_revision = adopted['revision']
                    self.repository.save_scoped_cache(identity, expected, foundation_revision=foundation,
                        scope_revision=scope['scopeRevision'], alignment_version=baseline['alignmentVersion'],
                        scoped_report_revision=scoped_revision)
            if report['scopeSnapshot']['scopeRevision'] != scope['scopeRevision'] or not _complete(report):
                raise ValueError('Selected supporting scope is incomplete or changed')
            snapshot.append({'identity': deepcopy(identity), **expected, 'scopedReportRevision': scoped_revision})
            alignments = {a['itemId']: a for a in report['alignments']}
            components = context_components(report['items'], report['sharedContexts'])
            for item in report['items']:
                alignment = alignments[item['id']]
                context = _context_for(item, alignment, components[item['id']])
                included = _academic_item(item, alignment, context, identity, purpose)
                if included:
                    academic.append(included)
                else:
                    exclusions.append({'identity': deepcopy(identity), 'itemId': item['id'],
                                       'reason': alignment['status'] if context is not None else 'required_context_unusable'})
                    if purpose == 'tutor' and _qualified_request(discussion_query):
                        relations = sorted({finding['relation'] for finding in alignment['requirements']}
                                           | {dep['relation'] for dep in alignment.get('contextDependencies', [])})
                        qualified_relations = [relation for relation in relations if relation in
                                               ('outside_selected_scope', 'conflicting', 'unverified')]
                        if qualified_relations:
                            qualified.append({'id': item['id'], 'text': item['text'], 'itemType': item['itemType'],
                                'materialIdentity': deepcopy(identity), 'sourceType': identity['kind'],
                                'relation': qualified_relations[0] if len(qualified_relations) == 1 else 'mixed',
                                'relations': qualified_relations,
                                'qualification': 'Qualified discussion of ' + ', '.join(qualified_relations),
                                'scopeRevision': scope['scopeRevision'],
                                'alignment': deepcopy(alignment),
                                'supportingSourceRefs': deepcopy(item['supportingSourceRefs']),
                                'supportingSourceProofs': deepcopy(item.get('supportingSourceProofs', []))})
            if identity['kind'] == 'historical_exam':
                for paper in report['papers']:
                    paper_eligible = {item['id']: item for item in academic
                        if item['materialIdentity'] == identity and item.get('paperId') == paper['paperId']}
                    checked_topics = []
                    for topic in report['topics']:
                        finding = topic.get('alignment') or {}
                        requirements = set(topic.get('requirementIds', []))
                        if (finding.get('relation') != 'lecture_supported' or not requirements
                                or set(finding.get('originRequirementIds', [])) != requirements):
                            continue
                        if not any(item_id in paper_eligible and requirements & {
                                row['requirementId'] for row in paper_eligible[item_id]['alignment']['requirements']
                                if row['relation'] == 'lecture_supported'}
                                for item_id in topic.get('itemIds', [])):
                            continue
                        checked_topics.append({key: deepcopy(topic[key]) for key in
                            ('id', 'text', 'itemIds', 'requirementIds')}
                            | {'alignment': {key: deepcopy(finding.get(key)) for key in
                                ('relation', 'originRequirementIds', 'lectureSupportProofs',
                                 'supportingSourceProofs')}})
                    papers.append({'materialIdentity': deepcopy(identity), 'sourceRevision': expected['sourceRevision'],
                                   'paper': _structural_paper(paper), 'topics': checked_topics,
                                   'eligibleItemIds': sorted(paper_eligible),
                                   'itemParentIds': {item['id']: item.get('parentId') for item in report['items']
                                       if item.get('paperId') == paper['paperId']}})
        snap = {'version': 1, 'materials': snapshot}
        self.repository.assert_snapshot(snap, scope_revision=scope['scopeRevision'])
        return {'version': 1, 'purpose': purpose, 'scopeSnapshot': _scope_snapshot(scope), 'snapshot': snap,
                'academicItems': academic, 'qualifiedItems': qualified, 'structuralPapers': papers,
                'coverage': {'selectedMaterialCount': len(snapshot), 'excludedItems': exclusions}}


def historical_projection(packet):
    if not isinstance(packet, dict) or not isinstance(packet.get('academicItems'), list):
        raise ValueError('Checked supporting packet is required')
    eligible = {(item['materialIdentity']['materialId'], item['id']): item
                for item in packet['academicItems']
                if item.get('materialIdentity', {}).get('kind') == 'historical_exam'
                and item.get('relation', 'lecture_supported') == 'lecture_supported'}
    # The label is selected across all eligible instances before any paper is
    # projected, so upload/list order cannot decide capitalization.
    evidence = []
    for structural in packet.get('structuralPapers', []):
        identity, paper = structural['materialIdentity'], structural['paper']
        source_id = identity['materialId']
        parent_ids = structural.get('itemParentIds', {})
        question_ids = set(paper.get('questionIds', []))
        allowed = set(structural.get('eligibleItemIds', []))
        for topic in structural.get('topics', []):
            finding = topic.get('alignment') or {}
            if finding.get('relation') != 'lecture_supported': continue
            requirement_ids = set(topic.get('requirementIds', []))
            origin_requirement_ids = set(finding.get('originRequirementIds', []))
            if not requirement_ids or requirement_ids != origin_requirement_ids: continue
            votes = set()
            for item_id in topic.get('itemIds', []):
                if item_id not in allowed: continue
                item = eligible.get((source_id, item_id))
                if not item or item.get('paperId') != paper.get('paperId'): continue
                supported = {row['requirementId'] for row in item.get('alignment', {}).get('requirements', [])
                             if row.get('relation') == 'lecture_supported'}
                if not supported & requirement_ids: continue
                root, seen = item_id, set()
                while parent_ids.get(root) and root not in seen:
                    seen.add(root)
                    root = parent_ids[root]
                if root not in question_ids: continue
                votes.add(root)
            if votes:
                label = ' '.join(unicodedata.normalize('NFKC', topic['text']).split())
                if label:
                    evidence.append((source_id, paper['paperId'], label.casefold(), label,
                                     topic['id'], sorted(votes)))
    labels = {}
    for _, _, key, label, _, _ in evidence:
        labels[key] = min(labels.get(key, label), label)
    grouped = {}
    for source_id, paper_id, key, _, topic_id, votes in evidence:
        row = grouped.setdefault((source_id, paper_id), {}).setdefault(key, {'votes': set(), 'topicIds': set()})
        row['votes'].update(votes)
        row['topicIds'].add(topic_id)
    sources = {}
    for structural in packet.get('structuralPapers', []):
        identity, original = structural['materialIdentity'], structural['paper']
        source_id, paper_id = identity['materialId'], original['paperId']
        topics = grouped.get((source_id, paper_id), {})
        projected = _structural_paper(original)
        projected.pop('questionIds', None)
        projected['topicWeights'] = [
            {'topic': labels[key], 'questionCount': len(value['votes']),
             'originQuestionIds': sorted(value['votes']), 'topicIds': sorted(value['topicIds'])}
            for key, value in sorted(topics.items())]
        projected['difficultyDistribution'] = []
        source = sources.setdefault(source_id, {'sourceId': source_id, 'analysisVersion': 3, 'papers': []})
        source['papers'].append(projected)
    for source in sources.values(): source['papers'].sort(key=lambda row: row['paperId'])
    return [sources[key] for key in sorted(sources)]
