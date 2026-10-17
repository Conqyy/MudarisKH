"""Audio/notes evidence keeps originals separate from cleaned display text."""
import csv
import hashlib
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agents.audio_intelligence import AudioIntelligenceAgent
from src.supporting.contracts import validate_source_proof


def _source_module():
    assert importlib.util.find_spec('src.supporting.audio_sources') is not None, 'Audio/notes source preparation is missing'
    return importlib.import_module('src.supporting.audio_sources')


def build_audio_manifest(*args, **kwargs):
    return _source_module().build_audio_manifest(*args, **kwargs)


def build_notes_manifest(*args, **kwargs):
    return _source_module().build_notes_manifest(*args, **kwargs)


def extract_teaching_items(*args, **kwargs):
    return _source_module().extract_teaching_items(*args, **kwargs)


AUDIO = {'userId': 'u', 'courseId': 'c', 'kind': 'audio', 'materialId': 'recording'}
NOTES = {**AUDIO, 'kind': 'notes'}
DIGEST = hashlib.sha256(b'original recording bytes').hexdigest()


def transcript(segments):
    chunks = list(dict.fromkeys(s['chunkId'] for s in segments))
    voiced = [s for s in segments if s['text'].strip()]
    return {'text': ' '.join(s['text'] for s in segments if s['disposition'] == 'readable').strip(),
            'segments': segments, 'timingAvailable': bool(voiced) and all(s['timing'] is not None for s in voiced),
            'coverage': {'chunkIds': chunks, 'accountedChunkIds': chunks,
                         'unresolvedChunkIds': [s['chunkId'] for s in segments if s['disposition'] == 'uncertain'],
                         'complete': not any(s['disposition'] == 'uncertain' for s in segments)}}


def segment(text, *, chunk='chunk_000.mp3', timing=None, disposition='readable'):
    return {'chunkId': chunk, 'text': text, 'timing': timing, 'disposition': disposition}


def test_notes_keep_exact_unicode_and_whitespace_as_verbatim_evidence():
    original_notes = '  شرح الأستاذ: التَعَلُّم العميق — مهم!\n  Section ٣: trees  \n'
    manifest = build_notes_manifest(NOTES, original_notes)
    assert manifest['identity']['kind'] == 'notes'
    assert manifest['originalDigest'] == hashlib.sha256(original_notes.encode('utf-8')).hexdigest()
    assert all(u['timing'] is None for u in manifest['units'])
    assert ''.join(u['text'] for u in manifest['units']) == original_notes
    assert "[Student's typed notes" not in ''.join(u['text'] for u in manifest['units'])
    start = original_notes.index('التَعَلُّم')
    end = start + len('التَعَلُّم العميق')
    quote = {'type': 'text_span', 'ref': {'kind': 'notes', 'materialId': 'recording',
              'sourceRevision': manifest['sourceRevision'], 'unitId': manifest['units'][0]['unitId']},
             'field': 'text', 'start': start, 'end': end, 'quote': original_notes[start:end]}
    assert quote['quote'] == original_notes[quote['start']:quote['end']]
    assert validate_source_proof(quote, ref=quote['ref'], unit=manifest['units'][0]) == quote
    assert build_notes_manifest(NOTES, original_notes)['sourceRevision'] == manifest['sourceRevision']
    assert build_notes_manifest(NOTES, original_notes + ' ')['sourceRevision'] != manifest['sourceRevision']


def test_changed_transcription_on_same_recording_changes_revision_and_keeps_raw_losses():
    before = transcript([segment('Explain AVL trees.', timing={'startSeconds': 2.5, 'endSeconds': 4}),
                         segment('Computer-science university lecture, mixed Arabic and English.', disposition='nonacademic'),
                         segment('объяснить дерево', disposition='uncertain')])
    old_manifest = build_audio_manifest(AUDIO, original_digest=DIGEST, transcript=before)
    after = transcript([segment('Explain red-black trees.', timing={'startSeconds': 2.5, 'endSeconds': 4}),
                        *before['segments'][1:]])
    changed_manifest = build_audio_manifest(AUDIO, original_digest=DIGEST, transcript=after)
    assert old_manifest['sourceRevision'] != changed_manifest['sourceRevision']
    assert old_manifest['originalDigest'] == changed_manifest['originalDigest'] == DIGEST
    assert [u['text'] for u in old_manifest['units']] == [s['text'] for s in before['segments']]
    assert old_manifest['units'][0]['timing'] == {'startSeconds': 2.5, 'endSeconds': 4}
    assert old_manifest['coverage']['unresolvedUnitIds'] == [old_manifest['units'][2]['unitId']]
    assert old_manifest['coverage']['complete'] is False


def test_untimed_fallback_and_empty_chunk_are_never_invented_as_verified_speech():
    source = transcript([segment('A whole response with no provider segment timing.'),
                         segment('', chunk='chunk_001.mp3', disposition='uncertain')])
    manifest = build_audio_manifest(AUDIO, original_digest=DIGEST, transcript=source)
    assert [u['timing'] for u in manifest['units']] == [None, None]
    assert manifest['units'][1]['disposition'] == 'uncertain'
    assert manifest['coverage']['complete'] is False
    with pytest.raises(ValueError, match='(?i)incomplete|chunk|coverage'):
        build_audio_manifest(AUDIO, original_digest=DIGEST, transcript={**source, 'coverage': {**source['coverage'], 'complete': True}})
    with pytest.raises(ValueError, match='(?i)timing'):
        build_audio_manifest(AUDIO, original_digest=DIGEST, transcript={**source, 'timingAvailable': True})


def test_empty_provider_outcome_requires_uncertainty_without_no_speech_evidence():
    source = transcript([segment('', disposition='blank')])
    with pytest.raises(ValueError, match='(?i)empty|speech|uncertain'):
        build_audio_manifest(AUDIO, original_digest=DIGEST, transcript=source)


def test_empty_uncertain_segment_has_no_verified_timing_in_manifest():
    source = transcript([segment('', disposition='uncertain')])
    assert source['timingAvailable'] is False
    manifest = build_audio_manifest(AUDIO, original_digest=DIGEST, transcript=source)
    assert manifest['units'][0]['timing'] is None
    assert manifest['coverage']['complete'] is False
    with pytest.raises(ValueError, match='(?i)timing'):
        build_audio_manifest(AUDIO, original_digest=DIGEST, transcript={**source, 'timingAvailable': True})


def _transcribe_fixture(monkeypatch, tmp_path, *, boundaries, responses):
    """Only external ffmpeg/Groq transport is replaced; parser and cleaner stay real."""
    import src.agents.audio_intelligence as audio_module

    events = []
    response_iter = iter(responses)

    class Transport:
        def create(self, **kwargs):
            events.append(('provider', Path(kwargs['file'].name).name, kwargs['response_format']))
            return next(response_iter)

    monkeypatch.setattr(audio_module.shutil, 'which', lambda name: 'ffmpeg')
    monkeypatch.setattr(audio_module.settings, 'GROQ_API_KEY', 'test-only-key')
    monkeypatch.setattr(audio_module, 'OpenAI', lambda **kwargs: SimpleNamespace(audio=SimpleNamespace(
        transcriptions=SimpleNamespace(create=Transport().create))))

    def ffmpeg(args, **kwargs):
        list_path = Path(args[args.index('-segment_list') + 1])
        template = Path(args[-1])
        with list_path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            for index, (start, end) in enumerate(boundaries):
                chunk = Path(str(template).replace('%03d', f'{index:03d}'))
                chunk.write_bytes(b'chunk')
                writer.writerow([chunk.name, start, end])
        return SimpleNamespace(returncode=0, stderr=b'')

    monkeypatch.setattr(audio_module.subprocess, 'run', ffmpeg)
    return events


def test_measured_chunk_starts_and_missing_provider_time(monkeypatch, tmp_path):
    events = _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 598.4), (598.4, 1201.7)], responses=[
        SimpleNamespace(segments=[SimpleNamespace(text='First exact sentence', start=1.2, end=2.4)]),
        SimpleNamespace(segments=[SimpleNamespace(text='Second exact sentence', start=3.0, end=5.0),
                                  SimpleNamespace(text='No timestamp sentence', start=None, end=None)]),
    ])
    agent = object.__new__(AudioIntelligenceAgent)
    result = agent.transcribe_audio_source('fixture.mp3')
    assert [s['timing'] for s in result['segments']] == [
        {'startSeconds': 1.2, 'endSeconds': 2.4},
        {'startSeconds': 601.4, 'endSeconds': 603.4}, None]
    assert [s['text'] for s in result['segments']] == ['First exact sentence', 'Second exact sentence', 'No timestamp sentence']
    assert result['timingAvailable'] is False
    assert result['coverage']['complete'] is True
    assert len(events) == 2


def test_cleaned_display_does_not_erase_provider_segments_or_uncertainty(monkeypatch, tmp_path):
    phrase = 'Computer-science university lecture, mixed Arabic and English.'
    _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 120)], responses=[
        SimpleNamespace(segments=[SimpleNamespace(text='Trees are important.', start=1, end=2),
                                  SimpleNamespace(text=phrase, start=3, end=4),
                                  SimpleNamespace(text='Trees are important.', start=5, end=6),
                                  SimpleNamespace(text='деревья', start=7, end=8)])])
    agent = object.__new__(AudioIntelligenceAgent)
    result = agent.transcribe_audio_source('fixture.mp3')
    assert result['text'] == 'Trees are important'
    assert [s['text'] for s in result['segments']] == ['Trees are important.', phrase, 'Trees are important.', 'деревья']
    assert [s['disposition'] for s in result['segments']] == ['readable', 'nonacademic', 'uncertain', 'uncertain']
    assert result['coverage']['complete'] is False


def test_empty_provider_reply_is_uncertain_and_failed_chunk_cannot_publish(monkeypatch, tmp_path):
    _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 90)], responses=[SimpleNamespace(segments=[], text='')])
    agent = object.__new__(AudioIntelligenceAgent)
    result = agent.transcribe_audio_source('fixture.mp3')
    assert len(result['segments']) == 1
    assert result['segments'][0]['text'] == ''
    assert result['segments'][0]['disposition'] == 'uncertain'
    assert result['timingAvailable'] is False
    assert result['coverage']['complete'] is False


def test_whole_response_fallback_keeps_words_without_inventing_timing(monkeypatch, tmp_path):
    _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 60)], responses=[
        SimpleNamespace(segments=[], text='Exact fallback wording.')])
    result = object.__new__(AudioIntelligenceAgent).transcribe_audio_source('fixture.mp3')
    assert result['segments'] == [{'chunkId': 'chunk_000.mp3', 'text': 'Exact fallback wording.',
                                   'timing': None, 'disposition': 'readable'}]
    assert result['timingAvailable'] is False
    assert result['coverage']['complete'] is True


def test_malformed_provider_times_remain_null_without_losing_words(monkeypatch, tmp_path):
    _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 60)], responses=[
        SimpleNamespace(segments=[SimpleNamespace(text='No reliable time', start=-1, end=4),
                                  SimpleNamespace(text='Out of range', start=3, end=100),
                                  SimpleNamespace(text='Zero length', start=0, end=0)])])
    result = object.__new__(AudioIntelligenceAgent).transcribe_audio_source('fixture.mp3')
    assert [s['timing'] for s in result['segments']] == [None, None, None]
    assert [s['disposition'] for s in result['segments']] == ['readable', 'readable', 'readable']


def test_transcription_budget_hooks_surround_each_return_before_parsing(monkeypatch, tmp_path):
    events = _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 90), (90, 180)], responses=[
        SimpleNamespace(segments=[SimpleNamespace(text='First', start=1, end=2)]),
        SimpleNamespace(segments=[SimpleNamespace(text='Second', start=1, end=2)]),
    ])
    agent = object.__new__(AudioIntelligenceAgent)
    result = agent.transcribe_audio_source('fixture.mp3', before_call=lambda: events.append(('before',)),
                                           on_response=lambda: events.append(('returned',)))
    assert result['text'] == 'First\n\nSecond'
    assert events == [('before',), ('provider', 'chunk_000.mp3', 'verbose_json'), ('returned',),
                      ('before',), ('provider', 'chunk_001.mp3', 'verbose_json'), ('returned',)]


def test_transcription_hook_failure_propagates_and_invalid_reply_spends_call(monkeypatch, tmp_path):
    events = _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 90)], responses=[SimpleNamespace(segments='invalid')])
    agent = object.__new__(AudioIntelligenceAgent)
    with pytest.raises(ValueError, match='segments'):
        agent.transcribe_audio_source('fixture.mp3', before_call=lambda: events.append(('before',)),
                                      on_response=lambda: events.append(('returned',)))
    assert [e[0] for e in events] == ['before', 'provider', 'returned']
    events.clear()
    _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 90)], responses=[SimpleNamespace(segments=[])])
    with pytest.raises(RuntimeError, match='budget'):
        agent.transcribe_audio_source('fixture.mp3', before_call=lambda: (_ for _ in ()).throw(RuntimeError('budget exhausted')))


def test_malformed_or_overlapping_measured_chunk_list_fails_before_provider(monkeypatch, tmp_path):
    events = _transcribe_fixture(monkeypatch, tmp_path, boundaries=[(0, 100), (99, 200)], responses=[])
    with pytest.raises(ValueError, match='(?i)chunk|boundar|overlap'):
        object.__new__(AudioIntelligenceAgent).transcribe_audio_source('fixture.mp3')
    assert events == []


def test_structured_transcription_requires_configured_provider_key(monkeypatch):
    import src.agents.audio_intelligence as audio_module
    monkeypatch.setattr(audio_module.settings, 'GROQ_API_KEY', '')
    with pytest.raises(RuntimeError, match='GROQ_API_KEY'):
        object.__new__(AudioIntelligenceAgent).transcribe_audio_source('fixture.mp3')


def test_notes_reanalysis_reaches_late_statement_and_preserves_note_source():
    from .test_source_context import source_scope
    from src.services.source_evidence import SourceEvidence
    original_notes = ('Administration and schedule. ' * 4500) + ' \nProfessor said AVL rotations are on the midterm.'
    manifest = build_notes_manifest(NOTES, original_notes)
    late = 'Professor said AVL rotations are on the midterm.'

    class Provider:
        def __init__(self):
            self.calls = []
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            self.calls.append(kwargs)
            request = json.loads(kwargs['messages'][1]['content'][0]['text'])
            source = request['source']
            window = source['ranges'][0]
            items, topics = [], []
            if late in window['text']:
                start = window['start'] + window['text'].index(late)
                proof = {'type': 'text_span', 'ref': source['ref'], 'field': 'text',
                         'start': start, 'end': start + len(late), 'quote': late}
                req = {'origin': proof, 'text': late, 'category': 'concept', 'proofs': [proof]}
                items = [{'origin': proof, 'itemType': 'emphasis', 'parent': None, 'text': late,
                          'printedLabel': None, 'printedMarks': None, 'questionType': None,
                          'choices': [], 'givenData': [], 'contextOrigins': [], 'proofs': [proof], 'requirements': [req]}]
                topics = [{'text': 'AVL rotations', 'items': [{'origin': proof, 'itemType': 'emphasis'}],
                           'requirements': [{'origin': proof, 'text': late, 'category': 'concept'}], 'proofs': [proof]}]
            row = {'disposition': 'readable' if items else 'nonacademic', 'pageRole': 'other',
                   'paper': None, 'items': items, 'sharedContexts': [], 'topics': topics}
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',
                message=SimpleNamespace(content=json.dumps(row, ensure_ascii=False)))])

    provider = Provider()
    reader = SourceEvidence(source_scope(['Algorithms: AVL trees']), object(), 'u', 'c', None, 'unused')
    checkpoints = []
    first = extract_teaching_items(manifest, client=provider, model='fixture', lecture_reader=reader,
                                   checkpoint=checkpoints.append, course_title='Algorithms')
    assert first['extractionCoverage']['complete'] is True
    assert first['items'][0]['itemType'] == 'emphasis'
    proof = first['items'][0]['supportingSourceProofs'][0]
    assert proof['quote'] == original_notes[proof['start']:proof['end']] == late
    assert proof['ref']['kind'] == 'notes'
    assert first['topics'][0]['requirementIds'] == [first['items'][0]['requirements'][0]['id']]
    assert any(json.loads(c['messages'][1]['content'][0]['text'])['source']['ranges'][0]['start'] >= 120000
               for c in provider.calls)
    again = extract_teaching_items(manifest, client=provider, model='fixture', lecture_reader=reader,
                                   checkpoint=lambda state: None, course_title='Algorithms')
    assert again['items'] == first['items']


def test_notes_extraction_interruption_reports_unresolved_coverage():
    from .test_source_context import source_scope
    from src.services.source_evidence import SourceEvidence
    manifest = build_notes_manifest(NOTES, 'Professor emphasized hashing and trees.')
    provider = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(RuntimeError('offline')))))
    reader = SourceEvidence(source_scope(['Algorithms: trees']), object(), 'u', 'c', None, 'unused')
    result = extract_teaching_items(manifest, client=provider, model='fixture', lecture_reader=reader,
                                    checkpoint=lambda state: None, course_title='Algorithms')
    assert result['extractionCoverage']['complete'] is False
    assert result['extractionCoverage']['unresolvedUnitIds'] == [manifest['units'][0]['unitId']]
