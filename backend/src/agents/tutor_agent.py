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
            },
        )
        self.model_id = settings.OPENROUTER_MODEL

    def _build_context(self, resources: dict) -> str:
        """Format the tutor's own resource bundle (documents, voice recordings,
        past exams) into grounding context."""
        ctx = []

        docs = resources.get("documents", [])
        texts = [d.get("extractedText", "") for d in docs if d.get("extractedText")]
        if texts:
            combined = "\n\n---\n\n".join([t[:4000] for t in texts[:4]])
            ctx.append("LECTURE DOCUMENT CONTENT:\n" + combined[:12000])
        for d in docs[:6]:
            a = d.get("analysis", {}) or {}
            topics_str = ", ".join(a.get("topics", [])[:20])
            defs = a.get("definitions", [])[:12]
            defs_str = "; ".join([f"{x['term']}: {x['definition']}" for x in defs if 'term' in x])
            if topics_str or defs_str:
                ctx.append(f"DOCUMENT TOPICS: {topics_str}\nKEY DEFINITIONS: {defs_str}")

        for r in resources.get("recordings", [])[:4]:
            ins = r.get("insights", {}) or {}
            summ = ins.get("summary", "")
            hints = ins.get("examHints", [])[:6]
            hints_str = "; ".join([h.get("hint", "") for h in hints])
            block = ""
            if summ:
                block += f"LECTURE SUMMARY ({r.get('title','recording')}): {summ}\n"
            if hints_str:
                block += f"PROFESSOR EXAM HINTS: {hints_str}"
            if block:
                ctx.append(block)

        for e in resources.get("past_exams", [])[:3]:
            a = e.get("analysis", {}) or {}
            weights = a.get("topicWeights", [])[:12]
            weights_str = ", ".join([f"{w.get('topic','')} ({w.get('weight',0):.0%})" for w in weights])
            if weights_str:
                ctx.append(f"PAST-EXAM TOPIC WEIGHTS ({e.get('title','exam')}): {weights_str}")

        # Tutorials: practice problems the student solves — include each problem
        # (what it asks + the method) so the tutor can walk through solving them.
        for t in resources.get("tutorials", [])[:4]:
            a = t.get("analysis", {}) or {}
            topics_str = ", ".join(a.get("topics", [])[:15])
            prob_lines = []
            for p in a.get("problems", [])[:10]:
                concept = (p.get("concept") or "").strip()
                statement = (p.get("statement") or "").strip()
                method = (p.get("method") or "").strip()
                line = "- " + (f"{concept}: " if concept else "") + statement
                if method:
                    line += f" (method: {method})"
                prob_lines.append(line)
            block = f"TUTORIAL ({t.get('title','tutorial')})"
            if topics_str:
                block += f" — topics: {topics_str}"
            if prob_lines:
                block += "\nPractice problems:\n" + "\n".join(prob_lines)
            if topics_str or prob_lines:
                ctx.append(block)

        return "\n\n".join(ctx)[:18000] or "No course materials have been analyzed yet."

    def reply(self, resources: dict, messages: list) -> str:
        """Answer the student's latest message as a course tutor, grounded in the
        tutor's own resource bundle."""
        course = resources.get("course", {}) or {}
        course_title = course.get("title") or course.get("code") or "this course"
        logger.info(f"AI tutor replying for course: {course_title}")

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
        return (response.choices[0].message.content or "").strip()
