from src.services.source_evidence import evidence_content, SOURCE_POLICY
from openai import OpenAI
import json
import re
import logging
import csv
import glob
import math
import os
import shutil
import subprocess
import tempfile
from collections import namedtuple
from src.config import settings
from src.config import prompts
from src.utils.ai_retry import chat_with_retry, call_with_retry
from src.utils.ai_contracts import validate_analysis, response_text
from src.utils.text_normalization import excerpt
from src.utils.media_safety import FFMPEG_INPUT_OPTIONS
from src.utils.course_foundation import build_foundation_context

logger = logging.getLogger("MudarisAudioIntel")

# Lightweight segment so Groq's JSON and faster-whisper's objects share one
# formatter (_format_segments reads .text / .start / .end).
_Seg = namedtuple("_Seg", ["text", "start", "end"])


class AudioIntelligenceAgent:
    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://mudaris-app.com",
                "X-Title": "Mudaris AI Engine"
            }, timeout=90.0, max_retries=0,
        )
        self.model_id = settings.OPENROUTER_MODEL

    @staticmethod
    def _format_segments(segments) -> str:
        """Turn raw Whisper segments into readable text: group them into
        paragraphs, breaking on noticeable pauses, instead of one giant blob."""
        paragraphs, current, prev_end, words = [], [], None, 0
        for seg in segments:
            text = (getattr(seg, "text", "") or "").strip()
            if not text:
                continue
            start = getattr(seg, "start", None)
            # New paragraph on a >2.5s pause, or every ~120 words, for readability.
            if current and (
                (prev_end is not None and start is not None and start - prev_end > 2.5)
                or words > 120
            ):
                paragraphs.append(" ".join(current))
                current, words = [], 0
            current.append(text)
            words += len(text.split())
            prev_end = getattr(seg, "end", prev_end)
        if current:
            paragraphs.append(" ".join(current))
        return "\n\n".join(paragraphs)

    def transcribe_audio(self, file_path: str) -> str:
        """Transcribe with Groq's hosted Whisper-large-v3 — the single source of
        truth (no local fallback, so quality is always the hosted model)."""
        logger.info(f"Transcribing audio (Groq): {file_path}")
        if not getattr(settings, "GROQ_API_KEY", ""):
            raise RuntimeError(
                "Transcription requires GROQ_API_KEY — set it in backend/.env."
            )
        return self.transcribe_audio_source(file_path)['text']

    def _transcribe_groq(self, file_path: str) -> str:
        """Compatibility entry point for callers expecting the display transcript."""
        return self.transcribe_audio_source(file_path)['text']

    @staticmethod
    def _measured_chunks(list_path, chunks):
        """Bind produced files to ffmpeg's measured segment boundaries."""
        try:
            with open(list_path, encoding='utf-8', newline='') as stream:
                rows = list(csv.reader(stream))
        except (OSError, UnicodeError, csv.Error) as exc:
            raise ValueError('Missing or invalid audio chunk boundaries') from exc
        if len(rows) != len(chunks):
            raise ValueError('Audio chunk boundary count differs from produced chunks')
        measured, previous_end = [], None
        for index, (row, chunk) in enumerate(zip(rows, chunks)):
            if len(row) != 3 or row[0] != os.path.basename(chunk):
                raise ValueError('Audio chunk boundary does not match a produced chunk')
            try:
                start, end = float(row[1]), float(row[2])
            except ValueError as exc:
                raise ValueError('Invalid audio chunk boundary') from exc
            if (not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start
                    or (index == 0 and start != 0) or (previous_end is not None and start < previous_end)):
                raise ValueError('Malformed or overlapping audio chunk boundaries')
            measured.append((chunk, start, end))
            previous_end = end
        return measured

    @staticmethod
    def _actual_timing(segment, chunk_start, chunk_end):
        get = segment.get if isinstance(segment, dict) else lambda key: getattr(segment, key, None)
        start, end = get('start'), get('end')
        if (isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end <= start or end > chunk_end - chunk_start + 0.01):
            return None
        return {'startSeconds': chunk_start + start, 'endSeconds': chunk_start + end}

    def transcribe_audio_source(self, file_path: str, *, before_call=None, on_response=None) -> dict:
        """Transcribe via Groq's hosted Whisper-large-v3 (GPU) — minutes, not
        hours. Preserve provider wording and measured timing separately from
        the cleaned transcript shown by legacy callers."""

        if not getattr(settings, 'GROQ_API_KEY', ''):
            raise RuntimeError('Transcription requires GROQ_API_KEY — set it in backend/.env.')

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found; needed to chunk audio for Groq.")

        client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            timeout=90.0, max_retries=0,
        )
        model = getattr(settings, "GROQ_WHISPER_MODEL", "whisper-large-v3")
        lang = getattr(settings, "WHISPER_LANGUAGE", "") or None
        seg_len = 600  # seconds per chunk

        workdir = tempfile.mkdtemp()
        try:
            chunk_tmpl = os.path.join(workdir, "chunk_%03d.mp3")
            chunk_list = os.path.join(workdir, 'chunks.csv')
            proc = subprocess.run(
                [ffmpeg, "-y", *FFMPEG_INPUT_OPTIONS, "-i", file_path, "-vn", "-ac", "1", "-ar", "16000",
                 "-f", "segment", "-segment_time", str(seg_len),
                 "-segment_list", chunk_list, "-segment_list_type", "csv",
                 "-c:a", "libmp3lame", "-q:a", "4", chunk_tmpl],
                capture_output=True,
                timeout=600,
            )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", "ignore")[-300:]
                raise RuntimeError(f"ffmpeg chunking failed: {err}")

            chunks = sorted(glob.glob(os.path.join(workdir, "chunk_*.mp3")))
            if not chunks:
                raise RuntimeError("No audio chunks were produced for Groq.")
            measured = self._measured_chunks(chunk_list, chunks)

            logger.info(f"Groq transcribing {len(chunks)} chunk(s) with {model}...")
            raw_segments, display_segments, previous_display = [], [], ''
            chunk_ids, unresolved = [], set()
            for ch, chunk_start, chunk_end in measured:
                chunk_id = os.path.basename(ch)
                chunk_ids.append(chunk_id)
                with open(ch, "rb") as fh:
                    def request(**kwargs):
                        if before_call is not None:
                            before_call()
                        return client.audio.transcriptions.create(**kwargs)
                    resp = call_with_retry(request,
                        model=model, file=fh, language=lang,
                        response_format="verbose_json",
                        # Short, English-only hint to bias language without
                        # giving Whisper a full Arabic sentence to echo. (A long
                        # Arabic prompt gets hallucinated/repeated verbatim into
                        # the transcript during silence — see _clean_segments.)
                        prompt="Computer-science university lecture, mixed Arabic and English.",
                        # Deterministic decoding reduces hallucinated text on
                        # silence/noise (a common source of stray languages).
                        temperature=0,
                    )
                if on_response is not None:
                    on_response()
                segs = getattr(resp, "segments", None)
                if segs is None and isinstance(resp, dict):
                    segs = resp.get("segments")
                if segs is not None and not isinstance(segs, (list, tuple)):
                    raise ValueError('Invalid provider segments')
                if not segs:
                    fallback = resp.get('text') if isinstance(resp, dict) else getattr(resp, 'text', None)
                    if fallback is not None and not isinstance(fallback, str):
                        raise ValueError('Invalid provider text')
                    segs = [{'text': fallback or '', 'start': None, 'end': None}]
                for segment in segs:
                    get = segment.get if isinstance(segment, dict) else lambda key: getattr(segment, key, None)
                    raw = get('text')
                    if not isinstance(raw, str):
                        raise ValueError('Invalid provider segment text')
                    timing = self._actual_timing(segment, chunk_start, chunk_end)
                    absolute_start = timing['startSeconds'] if timing is not None else None
                    absolute_end = timing['endSeconds'] if timing is not None else None
                    cleaned = self._clean_segments([_Seg(raw, absolute_start, absolute_end)])
                    if not raw.strip():
                        disposition = 'uncertain'
                    elif not self._is_arabic_or_english(raw):
                        disposition = 'uncertain'
                    elif not cleaned:
                        disposition = 'nonacademic' if any(p in raw for p in self._HALLUCINATION_PHRASES) else 'uncertain'
                    elif cleaned[0].text == previous_display:
                        disposition = 'uncertain'
                    else:
                        disposition = 'readable'
                        display_segments.append(cleaned[0])
                        previous_display = cleaned[0].text
                    if disposition == 'uncertain':
                        unresolved.add(chunk_id)
                    raw_segments.append({'chunkId': chunk_id, 'text': raw,
                                         'timing': timing, 'disposition': disposition})
            return {'text': self._format_segments(display_segments), 'segments': raw_segments,
                    'timingAvailable': all(s['timing'] is not None for s in raw_segments if s['text']),
                    'coverage': {'chunkIds': chunk_ids, 'accountedChunkIds': chunk_ids,
                                 'unresolvedChunkIds': [c for c in chunk_ids if c in unresolved],
                                 'complete': not unresolved}}
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # Phrases Whisper tends to hallucinate and repeat on silence/unclear audio:
    # the language-bias prompt (echoed verbatim) and subtitle-credit fillers it
    # learned from training on captioned video.
    _HALLUCINATION_PHRASES = [
        "محاضرة جامعية باللغتين العربية والإنجليزية",
        "المحاضرة جامعية باللغتين العربية والإنجليزية",
        "المحضرة جامعية باللغتين العربية والإنجليزية",
        "المحضرة جامعية باللغتين العربية والإنجليزي",
        "Computer-science university lecture, mixed Arabic and English.",
        "University lecture in Arabic and English.",
        "المترجم للقناة",
    ]

    @staticmethod
    def _clean_segments(segments):
        """Remove prompt-echo / subtitle-credit hallucinations and collapse
        repetition loops.

        Whisper floods low-confidence audio with the bias prompt repeated dozens
        of times, which buries (and out-weights) the professor's actual speech.
        We strip those phrases from each segment, drop what's left empty, and
        collapse immediate duplicate lines (the hallucination repeats a line)."""
        phrases = AudioIntelligenceAgent._HALLUCINATION_PHRASES
        cleaned, prev = [], ""
        for s in segments:
            text = s.text or ""
            for p in phrases:
                text = text.replace(p, " ")
            text = re.sub(r"\s+", " ", text).strip()
            text = text.strip(" .،,-—")
            # Keep only if something real (a letter/digit) remains.
            if not text or not re.search(r"[0-9A-Za-z؀-ۿ]", text):
                continue
            if text == prev:  # collapse immediate repeats
                continue
            prev = text
            cleaned.append(_Seg(text, s.start, s.end))
        return cleaned

    @staticmethod
    def _is_arabic_or_english(text: str) -> bool:
        """True if the text is predominantly Arabic and/or Latin (English) script.
        Used to discard segments Whisper mis-transcribed into another language."""
        letters = [c for c in (text or "") if c.isalpha()]
        if not letters:
            return True  # numbers/punctuation only — keep
        allowed = 0
        for c in letters:
            cp = ord(c)
            is_latin = (0x41 <= cp <= 0x5A) or (0x61 <= cp <= 0x7A) or (0xC0 <= cp <= 0x24F)
            is_arabic = (
                0x0600 <= cp <= 0x06FF or 0x0750 <= cp <= 0x077F
                or 0x08A0 <= cp <= 0x08FF or 0xFB50 <= cp <= 0xFDFF
                or 0xFE70 <= cp <= 0xFEFF
            )
            if is_latin or is_arabic:
                allowed += 1
        return allowed / len(letters) >= 0.5

    def analyze_transcript(self, transcript: str, course_title: str,
                           document_insights: list = None, *, lecture_evidence: dict | None = None) -> dict:
        logger.info("Analyzing transcript")

        # Feed (almost) the whole transcript so the summary covers the ENTIRE
        # lecture, not just the first ~15 min. Gemini Pro has a large context.
        truncated = excerpt(transcript, 120000)
        reference = build_foundation_context(document_insights)
        grounding = (
            '\n\nUse the lecture document reference to resolve academic terminology, '
            'identify taught chapters, and relate professor hints to course concepts. '
            'The transcript remains the primary evidence of what the professor actually said. '
            'Preserve verbatim transcript quotes; never add document-only claims to the '
            'professor\'s statements or invent exam hints. Describe unsupported or out-of-scope '
            'discussion honestly in the existing summary/chapter fields rather than forcing '
            'course alignment. Keep the existing output schema.\n\n' + reference
            if reference else ''
        )

        from src.utils.json_parse import parse_with_retry

        def _call(reminder: str) -> str:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": prompts.AUDIO_INTELLIGENCE_SYSTEM_PROMPT + reminder + (SOURCE_POLICY if lecture_evidence is not None else ""),
                    },
                    {
                        "role": "user",
                        "content": evidence_content(f"Course: {course_title}{grounding}\n\n---LECTURE TRANSCRIPT---\n{truncated}", lecture_evidence),
                    },
                ],
                temperature=0.1,
                # Room for a thorough whole-lecture summary + chapters/hints.
                max_tokens=max(settings.OPENROUTER_MAX_TOKENS, 16000),
            )
            return response_text(response)

        result = parse_with_retry(
            _call,
            required_keys=("chapterMapping", "examHints", "keyEmphasis", "summary"),
            label="audio analysis",
            validator=lambda data: validate_analysis('audio', data),
        )
        if not isinstance(result.get("summary"), str):
            result["summary"] = ""

        chapters = result.get("chapterMapping") or []
        hints = result.get("examHints") or []
        emphasis = result.get("keyEmphasis") or []
        if not chapters and not hints and not emphasis and not result["summary"].strip():
            raise RuntimeError(
                "The AI returned an empty audio analysis. Try re-analyzing — "
                "the model may have been overloaded or the transcript too short."
            )

        result['_contextCoverage'] = {'characters': len(transcript), 'includedCharacters': len(truncated), 'excerpted': len(transcript) > 120000}
        return result
