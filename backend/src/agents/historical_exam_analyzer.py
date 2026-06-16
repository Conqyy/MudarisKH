from openai import OpenAI
import json
import io
import logging
from src.config import settings
from src.config import prompts
from src.utils.ai_retry import chat_with_retry

logger = logging.getLogger("MudarisHistAnalyzer")


class HistoricalExamAnalyzer:
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

    def extract_exam_text(self, file_bytes: bytes) -> str:
        # Robust extraction: PyMuPDF first (handles font encodings PyPDF2 fails
        # on), with PyPDF2 as a fallback.
        from src.utils.pdf_extract import extract_pdf_text
        return extract_pdf_text(file_bytes)

    def analyze_exam(self, text: str, course_title: str, image_uris: list = None,
                     document_insights: list = None) -> dict:
        logger.info(f"Analyzing historical exam for course: {course_title}"
                    + (f" (+{len(image_uris)} page images)" if image_uris else ""))

        truncated = text[:15000]

        from src.utils.json_parse import parse_with_retry

        def _user_content():
            # When page images are available, send them so the model can SEE
            # equations, diagrams, figures, and code — not just extracted text.
            if image_uris:
                parts = [{
                    "type": "text",
                    "text": (
                        f"Course: {course_title}\n\nThe exam pages are shown as images below"
                        " (read the equations, diagrams, figures, and code in them)."
                        + (f"\n\n---EXTRACTED TEXT (for reference)---\n{truncated}" if truncated.strip() else "")
                    ),
                }]
                for uri in image_uris[:8]:
                    parts.append({"type": "image_url", "image_url": {"url": uri}})
                return parts
            return f"Course: {course_title}\n\n---EXAM TEXT---\n{truncated}"

        def _call(reminder: str) -> str:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[
                    {
                        "role": "system",
                        "content": prompts.HISTORICAL_EXAM_SYSTEM_PROMPT + reminder,
                    },
                    {"role": "user", "content": _user_content()},
                ],
                temperature=0.1,
                max_tokens=settings.OPENROUTER_MAX_TOKENS,
            )
            return (response.choices[0].message.content or "").strip()

        result = parse_with_retry(
            _call,
            required_keys=(
                "topicWeights",
                "questionTypes",
                "difficultyDistribution",
                "gradingBlueprint",
                "patterns",
                "totalQuestions",
            ),
            label="historical exam analysis",
        )
        # gradingBlueprint is a string, not a list — fix default if missing
        if not isinstance(result.get("gradingBlueprint"), str):
            result["gradingBlueprint"] = ""

        topics = result.get("topicWeights") or []
        qtypes = result.get("questionTypes") or []
        patterns = result.get("patterns") or []
        if not topics and not qtypes and not patterns:
            raise RuntimeError(
                "The AI returned an empty exam analysis. Try re-uploading or "
                "re-analyzing — the model may have been overloaded."
            )

        # Scope check: decide HERE (at analysis time) whether each of this past
        # exam's topics is still covered by the course's current lecture
        # documents. The result is stored on the analysis so the generator just
        # reads the flag — it never re-decides scope itself.
        self.tag_topic_scope(result, document_insights)

        return result

    @staticmethod
    def tag_topic_scope(result: dict, document_insights: list) -> dict:
        """Annotate each topicWeight with inScope (True/False) against the course's
        current lecture documents, and add a top-level outOfCourseTopics list.
        If no documents are available, scope is left undetermined (inScope=None)."""
        from src.utils.topic_scope import course_scope_from_docs, topic_in_scope

        topics = result.get("topicWeights") or []
        _, words = course_scope_from_docs(document_insights)
        out_of_course = []
        for w in topics:
            name = w.get("topic", "")
            if not words:                 # no documents → can't judge scope
                w["inScope"] = None
                continue
            in_scope = topic_in_scope(name, words)
            w["inScope"] = in_scope
            if not in_scope and name:
                out_of_course.append(name)
        result["outOfCourseTopics"] = out_of_course
        result["scopeChecked"] = bool(words)
        if out_of_course:
            logger.info(f"Past exam: {len(out_of_course)} topic(s) no longer in the course: {', '.join(out_of_course)}")
        return result
