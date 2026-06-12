from openai import OpenAI
import json
import re
import logging
from collections import namedtuple
from src.config import settings
from src.config import prompts
from src.utils.ai_retry import chat_with_retry

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
            }
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
        return self._transcribe_groq(file_path)

    def _transcribe_groq(self, file_path: str) -> str:
        """Transcribe via Groq's hosted Whisper-large-v3 (GPU) — minutes, not
        hours. Long files are split into ~10-min, 16 kHz mono chunks so each
        stays well under the API's upload-size limit, then stitched back."""
        import os
        import glob
        import shutil
        import tempfile
        import subprocess

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("ffmpeg not found; needed to chunk audio for Groq.")

        client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        model = getattr(settings, "GROQ_WHISPER_MODEL", "whisper-large-v3")
        lang = getattr(settings, "WHISPER_LANGUAGE", "") or None
        seg_len = 600  # seconds per chunk

        workdir = tempfile.mkdtemp()
        try:
            chunk_tmpl = os.path.join(workdir, "chunk_%03d.mp3")
            proc = subprocess.run(
                [ffmpeg, "-y", "-i", file_path, "-vn", "-ac", "1", "-ar", "16000",
                 "-f", "segment", "-segment_time", str(seg_len),
                 "-c:a", "libmp3lame", "-q:a", "4", chunk_tmpl],
                capture_output=True,
            )
            if proc.returncode != 0:
                err = (proc.stderr or b"").decode("utf-8", "ignore")[-300:]
                raise RuntimeError(f"ffmpeg chunking failed: {err}")

            chunks = sorted(glob.glob(os.path.join(workdir, "chunk_*.mp3")))
            if not chunks:
                raise RuntimeError("No audio chunks were produced for Groq.")

            logger.info(f"Groq transcribing {len(chunks)} chunk(s) with {model}...")
            all_segs = []
            for i, ch in enumerate(chunks):
                offset = i * seg_len
                with open(ch, "rb") as fh:
                    resp = client.audio.transcriptions.create(
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
                segs = getattr(resp, "segments", None)
                if segs is None and isinstance(resp, dict):
                    segs = resp.get("segments")
                if segs:
                    for s in segs:
                        get = (lambda k: s.get(k) if isinstance(s, dict) else getattr(s, k, None))
                        all_segs.append(_Seg(
                            get("text") or "",
                            (get("start") or 0) + offset,
                            (get("end") or 0) + offset,
                        ))
                else:
                    txt = getattr(resp, "text", "") or (resp.get("text") if isinstance(resp, dict) else "")
                    if txt:
                        all_segs.append(_Seg(txt, offset, offset))
            # Drop any segment written in a clearly non-Arabic / non-English
            # script (e.g. CJK, Cyrillic, Devanagari) — stray mis-detections.
            all_segs = [s for s in all_segs if self._is_arabic_or_english(s.text)]
            # Strip Whisper's prompt-echo / subtitle-credit hallucinations and
            # collapse repetition loops that otherwise bury the real speech.
            all_segs = self._clean_segments(all_segs)
            return self._format_segments(all_segs)
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

    def analyze_transcript(self, transcript: str, course_title: str) -> dict:
        logger.info(f"Analyzing transcript for course: {course_title}")

        # Feed (almost) the whole transcript so the summary covers the ENTIRE
        # lecture, not just the first ~15 min. Gemini Pro has a large context.
        truncated = transcript[:120000]

        from src.utils.json_parse import parse_with_retry

        def _call(reminder: str) -> str:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": prompts.AUDIO_INTELLIGENCE_SYSTEM_PROMPT + reminder,
                    },
                    {
                        "role": "user",
                        "content": f"Course: {course_title}\n\n---LECTURE TRANSCRIPT---\n{truncated}",
                    },
                ],
                temperature=0.1,
                # Room for a thorough whole-lecture summary + chapters/hints.
                max_tokens=max(settings.OPENROUTER_MAX_TOKENS, 16000),
            )
            return (response.choices[0].message.content or "").strip()

        result = parse_with_retry(
            _call,
            required_keys=("chapterMapping", "examHints", "keyEmphasis", "summary"),
            label="audio analysis",
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

        return result
