from openai import OpenAI
import logging
from src.config import settings
from src.config import prompts
from src.utils.ai_retry import chat_with_retry

logger = logging.getLogger("MudarisTutor")


class AITutorAgent:
    """Model 5 — conversational tutor grounded in a course's materials
    (lecture documents, audio insights, and past-exam patterns)."""

    def __init__(self):
        self.client = OpenAI(
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_BASE_URL,
            default_headers={
                "HTTP-Referer": "https://mudaris-app.com",
                "X-Title": "Mudaris AI Engine",
            }, timeout=90.0, max_retries=0,
        )
        self.model_id = settings.OPENROUTER_MODEL

    def _build_context(self, resources: dict) -> str:
        """Format the tutor's own resource bundle (documents, voice recordings,
        past exams) into grounding context."""
        from src.utils.text_normalization import budget_sources
        sources = []
        for kind in ('documents', 'recordings', 'past_exams', 'tutorials'):
            for index, row in enumerate(resources.get(kind, []) or []):
                if not isinstance(row, dict):
                    raise ValueError('Invalid tutor resource')
                # Allocate raw excerpts and structured analysis independently so
                # a long lecture cannot suppress later selected sources.
                label = f"{kind} {index + 1}: {row.get('title', '')}"
                raw = row.get('extractedText') or row.get('transcript') or ''
                if raw:
                    sources.append((label + ' content', raw))
                analysis = row.get('analysis') or row.get('insights') or {}
                if analysis:
                    sources.append((label + ' analysis', analysis))
        context, coverage = budget_sources(sources, 18000)
        return context or 'No course materials have been analyzed yet.'

    def reply(self, resources: dict, messages: list) -> str:
        """Answer the student's latest message as a course tutor, grounded in the
        tutor's own resource bundle."""
        course = resources.get("course", {}) or {}
        course_title = course.get("title") or course.get("code") or "this course"
        logger.info("Generating grounded tutor reply")

        context = self._build_context(resources)
        system = (
            prompts.AI_TUTOR_SYSTEM_PROMPT
            + f"\n\nCOURSE: {course_title}\n\n--- COURSE MATERIALS ---\n{context}"
        )

        history = [
            {"role": m.get("role", "user"), "content": str(m.get("content", ""))}
            for m in messages[-12:]
            if m.get("content")
        ]

        response = chat_with_retry(
            self.client,
            model=self.model_id,
            messages=[{"role": "system", "content": system}] + history,
            temperature=0.3,
            # Pro is a reasoning model — leave room for reasoning + the actual
            # reply, or content comes back empty.
            max_tokens=6000,
        )
        answer = (response.choices[0].message.content or "").strip()
        if not answer or getattr(response.choices[0], 'finish_reason', None) == 'length':
            raise RuntimeError('The tutor response was empty or incomplete. Please retry.')
        return answer
