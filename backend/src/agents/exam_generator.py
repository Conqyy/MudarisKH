from openai import OpenAI
import json
import re
import logging
from src.config import settings
from src.config import prompts
from src.utils.ai_retry import chat_with_retry

logger = logging.getLogger("MudarisExamGenerator")


def _as_text(item) -> str:
    """Coerce an analysis item to a display string. Some documents store
    topics / formulas / workedExamples as dicts (e.g. {"title":..,"solution":..})
    instead of plain strings — handle both so ", ".join(...) never crashes."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        for k in ("statement", "problem", "title", "name", "text", "description",
                  "example", "formula", "equation", "topic", "term", "concept", "skill"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        parts = [str(v).strip() for v in item.values()
                 if isinstance(v, (str, int, float)) and str(v).strip()]
        return " — ".join(parts) if parts else ""
    return str(item).strip() if item is not None else ""


def _join_texts(items, sep: str = ", ", limit: int | None = None) -> str:
    """Join a list of analysis items into a string, tolerating dict/non-string
    items (see _as_text). Replaces bare ", ".join(...) on raw analysis lists."""
    items = list(items or [])
    if limit is not None:
        items = items[:limit]
    return sep.join(t for t in (_as_text(i) for i in items) if t)


def _course_topic_list(document_insights: list) -> list:
    """The current course's topic whitelist (display only), from the lecture
    documents. Used as context for generation — the in/out-of-scope DECISION for
    past-exam topics is made by the Historical Exam Analyzer, not here."""
    seen, out = set(), []
    for doc in document_insights or []:
        title = re.sub(r"^\s*\d+\s*[-.)]\s*", "", (doc.get("documentTitle") or "")).strip()
        names = ([title] if title else []) + list(doc.get("topics", []) or [])
        for t in names:
            t = (t or "").strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                out.append(t)
    return out


class ExamGeneratorAgent:
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

    def compile_exam(self, academic_data: dict, topics: list, preference: str, exam_id: str, user_id: str = "sultan_123", course_id: str = "cs464") -> str:
        logger.info(f"Compiling custom LaTeX PDF structure for exam: {exam_id}")

        user_payload = f"""
        --- SYSTEM STATE DATA ---
        USER_ID: {user_id}
        COURSE_ID: {course_id}
        EXAM_ID: {exam_id}

        --- INPUT STUDY STREAMS ---
        Syllabus Chapters Selected: {academic_data.get('transcripts', '')[:3000]}
        Professor Voice Cues: {academic_data.get('cues', 'None provided')}
        Custom Target Topics Checklist: {", ".join(topics)}
        Student Overrides & Preferences: {preference}
        """

        response = chat_with_retry(
            self.client,
            model=self.model_id,
            messages=[
                {"role": "system", "content": prompts.EXAM_GEN_SYSTEM_PROMPT},
                {"role": "user", "content": user_payload}
            ],
            temperature=0.2,
            max_tokens=16000,
        )

        raw_tex = (response.choices[0].message.content or "").strip()
        raw_tex = self._sanitize_latex(raw_tex)

        raw_tex = raw_tex.replace("{{EXAM_ID}}", exam_id)
        raw_tex = raw_tex.replace("{{USER_ID}}", user_id)
        raw_tex = raw_tex.replace("{{COURSE_ID}}", course_id)

        return raw_tex.strip()

    def compile_enhanced_exam(self, academic_data: dict, topics: list, preference: str, exam_id: str,
                              user_id: str = "sultan_123", course_id: str = "cs464",
                              document_insights: list = None, audio_insights: list = None,
                              historical_analysis: list = None,
                              document_texts: list = None, historical_texts: list = None,
                              tutorial_insights: list = None, tutorial_texts: list = None,
                              total_marks: int = 40, exam_type: str = "Final") -> str:
        logger.info(f"Compiling ENHANCED LaTeX exam: {exam_id} ({exam_type}, {total_marks} marks)")

        university = (academic_data.get("university") or "Mudaris University").strip()

        lecture_content_section = ""
        if document_texts:
            # Keep this lean — large context is the main cause of slow generation
            combined = "\n\n---\n\n".join([t[:4000] for t in document_texts[:4]])
            lecture_content_section = f"\n--- LECTURE DOCUMENT CONTENT (PRIMARY SOURCE FOR QUESTIONS) ---\n{combined[:12000]}"

        doc_section = ""
        if document_insights:
            doc_parts = []
            for doc in document_insights:
                topics_str = _join_texts(doc.get("topics"), ", ", 20)
                formulas_str = _join_texts(doc.get("formulas"), ", ", 10)
                defs = doc.get("definitions", [])[:10]
                defs_str = "; ".join([f"{d['term']}: {d['definition']}" for d in defs if 'term' in d])
                diags = doc.get("diagrams", [])[:8]
                diag_str = "; ".join([d.get("name", "") for d in diags if d.get("name")])
                code = doc.get("codeSnippets", [])[:6]
                code_str = "; ".join([f"{c.get('language','')}: {c.get('purpose','')}" for c in code if c.get('purpose')])
                examples = _join_texts(doc.get("workedExamples"), ", ", 6)
                part = f"Topics: {topics_str}\nFormulas/equations: {formulas_str}\nDefinitions: {defs_str}"
                if diag_str:
                    part += f"\nDiagrams: {diag_str}"
                if code_str:
                    part += f"\nCode: {code_str}"
                if examples:
                    part += f"\nWorked examples: {examples}"
                doc_parts.append(part)
            doc_section = "\n--- DOCUMENT ANALYSIS SUMMARY ---\n" + "\n\n".join(doc_parts)

        # COURSE SCOPE: the current lecture documents' topics, shown as the
        # allow-list. Whether each PAST-EXAM topic is in/out of this scope is
        # decided by the Historical Exam Analyzer (stored as inScope per topic);
        # here we just present that decision to the model.
        course_topics = _course_topic_list(document_insights)
        scope_section = ""
        if course_topics:
            scope_section = (
                "\n--- ALLOWED COURSE TOPICS (HARD SCOPE — only generate questions "
                "on these; they come from the CURRENT lecture documents) ---\n"
                + ", ".join(course_topics[:60])
            )

        audio_section = ""
        if audio_insights:
            audio_parts = []
            for a in audio_insights:
                hints = a.get("examHints", [])[:10]
                hints_str = "\n".join([f"- [{h.get('confidence', 0):.1f}] {h.get('hint', '')}" for h in hints])
                emphasis = a.get("keyEmphasis", [])[:10]
                emph_str = "\n".join([f"- [{e.get('emphasisLevel', 'low')}] {e.get('topic', '')}" for e in emphasis])
                audio_parts.append(f"Exam Hints:\n{hints_str}\nKey Emphasis:\n{emph_str}")
            audio_section = "\n--- AUDIO INTELLIGENCE ---\n" + "\n\n".join(audio_parts)

        hist_section = ""
        if historical_analysis:
            hist_parts = []
            for h in historical_analysis:
                weights = h.get("topicWeights", [])[:15]
                # Use the in/out-of-scope decision the ANALYZER already made and
                # stored (inScope per topic). Topics removed from the syllabus
                # (inScope == False) are dropped and the remaining in-scope topics
                # are RENORMALIZED to sum to 100% so their share absorbs the
                # removed topics' weight.
                if any(w.get("inScope") is False for w in weights):
                    in_scope = [w for w in weights if w.get("inScope") is not False]
                    out_scope = [w for w in weights if w.get("inScope") is False]
                    total_in = sum(float(w.get("weight", 0) or 0) for w in in_scope) or 1.0
                    lines = [
                        f"- {w.get('topic', '')}: {float(w.get('weight', 0) or 0) / total_in:.0%}"
                        f" ({w.get('questionCount', 0)} questions in the old exam)"
                        for w in in_scope
                    ]
                    for w in out_scope:
                        lines.append(
                            f"- {w.get('topic', '')}: REMOVED FROM COURSE — not in the current "
                            "lecture documents; DO NOT ask this. Its questions are reassigned to the "
                            "in-scope topics above (keep the same question type and marks)."
                        )
                    weights_str = "\n".join(lines)
                    weights_str += (
                        "\n(The in-scope percentages above are renormalized to total 100% over the "
                        "topics still in the course — distribute questions/marks by these.)"
                    )
                else:
                    weights_str = "\n".join([
                        f"- {w.get('topic', '')}: {w.get('weight', 0):.0%} ({w.get('questionCount', 0)} questions)"
                        for w in weights
                    ])
                qtypes = h.get("questionTypes", [])[:10]
                # Give the EXACT count of each question type (not just %), so the
                # generated exam reproduces the same number of MCQs, etc.
                qtypes_str = "\n".join([
                    f"  * {q.get('type', '')}: EXACTLY {q.get('count', 0)} question(s)"
                    + (f" — style: {q.get('style')}" if q.get('style') else "")
                    for q in qtypes
                ])
                total_q = h.get("totalQuestions", 0)
                skills_str = _join_texts(h.get("skills"), ", ", 10)
                patterns_str = "\n".join([f"  - {p}" for p in h.get("patterns", [])[:8]])
                part = f"Total questions on this exam: {total_q}\n"
                part += f"Topic Weights:\n{weights_str}\n"
                part += f"Question Types — REPRODUCE THE SAME TYPES AND THE SAME NUMBER OF EACH:\n{qtypes_str}"
                if skills_str:
                    part += f"\nSkills tested: {skills_str}"
                if patterns_str:
                    part += f"\nFormat/structure patterns (replicate these):\n{patterns_str}"
                part += f"\nGrading blueprint: {h.get('gradingBlueprint', 'N/A')}"
                hist_parts.append(part)
            hist_section = (
                "\n--- PAST-EXAM PATTERNS (match the EXACT question types and the EXACT number "
                "of each type — especially the MCQ count — plus the grading weights, topic "
                "weights, and overall format/layout) ---\n" + "\n\n".join(hist_parts)
            )

        hist_raw_section = ""
        if historical_texts:
            combined_hist = "\n\n---\n\n".join([t[:5000] for t in historical_texts[:2]])
            hist_raw_section = (
                "\n--- SELECTED PAST EXAM(S) RAW TEXT (match this format/sections/question-types AND "
                "the marks assigned to each question; weight topics by how heavily they appear here) ---\n"
                + combined_hist[:10000]
            )

        # Tutorials: practice-problem IDEAS only. They inform the CONTENT/style of
        # problem-solving questions (exam often reuses the idea with different
        # numbers) — but NEVER the marks, format, or question-type proportions.
        tutorial_section = ""
        tut_parts = []
        if tutorial_insights:
            for t in tutorial_insights:
                topics_str = _join_texts(t.get("topics"), ", ", 15)
                header = f"Topics practiced: {topics_str}" if topics_str else ""
                # New tutorial schema: a list of solvable problems.
                problems = t.get("problems", [])[:12]
                prob_lines = []
                for p in problems:
                    label = p.get("label", "")
                    statement = p.get("statement", "")
                    asks = _join_texts(p.get("asks"), "; ", 5)
                    concept = p.get("concept", "")
                    method = p.get("method", "")
                    given = p.get("given", "")
                    line = f"• {label}: {statement}".strip()
                    if asks:
                        line += f"\n   Asks: {asks}"
                    if concept:
                        line += f"\n   Concept: {concept}"
                    if method:
                        line += f"\n   Method: {method}"
                    if given:
                        line += f"\n   Example given-data (CHANGE these numbers): {str(given)[:300]}"
                    prob_lines.append(line)
                part = header
                if prob_lines:
                    part += ("\nPractice problems (re-create each with DIFFERENT numbers/values):\n"
                             + "\n".join(prob_lines))
                # Fallback for older tutorials analyzed with the document schema.
                if not problems:
                    examples = _join_texts(t.get("workedExamples"), ", ", 8)
                    if examples:
                        part += f"\nWorked problems / exercises: {examples}"
                formulas_str = _join_texts(t.get("formulas"), ", ", 10)
                if formulas_str:
                    part += f"\nFormulas/methods used: {formulas_str}"
                if part.strip():
                    tut_parts.append(part)
        if tutorial_texts:
            combined_tut = "\n\n---\n\n".join([t[:3000] for t in tutorial_texts[:3]])
            if combined_tut.strip():
                tut_parts.append("Raw tutorial problems:\n" + combined_tut[:8000])
        if tut_parts:
            tutorial_section = (
                "\n--- TUTORIALS (PRACTICE PROBLEMS the student solves — these are the kinds of "
                "problems that appear on the exam with DIFFERENT numbers/values. Re-create variants "
                "of these problems: keep the problem TYPE, concept, and method, but CHANGE the given "
                "numbers/data. Do NOT use tutorials to decide marks, format, or question-type "
                "proportions — those come ONLY from the past exams) ---\n" + "\n\n".join(tut_parts)
            )

        user_payload = f"""
        --- SYSTEM STATE DATA ---
        USER_ID: {user_id}
        COURSE_ID: {course_id}
        EXAM_ID: {exam_id}

        --- EXAM SPECIFICATION (REQUIRED) ---
        Exam Type: {exam_type}
        Total Marks: the exam MUST be worth exactly {total_marks} marks in total. Distribute marks across questions so they sum to {total_marks}. Show the marks for each question (e.g. "[5 marks]").
        Scope: a "Quiz" is short and focused (few questions), a "Midterm" is medium-length, a "Final" is comprehensive and covers more topics. Scale the number of questions to match the {exam_type} type and the {total_marks}-mark total.
        Title the exam header accordingly (e.g. "{exam_type} Examination").

        --- DOCUMENT HEADER (REQUIRED) ---
        The university name shown at the TOP of the exam MUST be EXACTLY this text, verbatim:
            {university}
        Do NOT invent a different university, and do NOT use any placeholder such as "University Name Placeholder", "[University Name]", or "Mudaris University of Technology". Use the exact text above as the university name in the header.

        --- INPUT STUDY STREAMS ---
        Syllabus Chapters Selected: {academic_data.get('transcripts', '')[:3000]}
        Professor Voice Cues: {academic_data.get('cues', 'None provided')}
        Custom Target Topics Checklist: {", ".join(topics)}
        Student Overrides & Preferences: {preference}
        {lecture_content_section}
        {doc_section}
        {scope_section}
        {audio_section}
        {hist_section}
        {hist_raw_section}
        {tutorial_section}
        """

        # Generate the exam, CONTINUING if the model runs out of output tokens
        # mid-document. A long exam (many questions + a rubrics block) frequently
        # exceeds a single response's token cap; instead of silently truncating
        # to 2-3 questions, we keep asking the model to continue from where it
        # stopped until it emits \end{document} + the </secret-rubrics> block (or
        # we hit a safety cap on continuations).
        messages = [
            {"role": "system", "content": prompts.ENHANCED_EXAM_GEN_SYSTEM_PROMPT},
            {"role": "user", "content": user_payload},
        ]

        full = ""
        MAX_CONTINUATIONS = 5
        for attempt in range(MAX_CONTINUATIONS + 1):
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=messages,
                temperature=0.2,
                max_tokens=16000,
            )
            choice = response.choices[0]
            chunk = (choice.message.content or "")
            full += chunk

            finish = getattr(choice, "finish_reason", None)
            is_complete = "\\end{document}" in full and "</secret-rubrics>" in full
            # Stop when the model finished naturally and the document is whole.
            if finish != "length" and is_complete:
                break
            # Also stop if it finished naturally but at least closed the document
            # (rubrics may be derived later by the endpoint as a fallback).
            if finish != "length" and "\\end{document}" in full and attempt >= 1:
                break
            if attempt == MAX_CONTINUATIONS:
                logger.warning(
                    f"Exam {exam_id}: hit continuation cap; using what we have."
                )
                break

            logger.info(
                f"Exam {exam_id}: output truncated (finish_reason={finish}); "
                f"continuing (attempt {attempt + 1})."
            )
            # Feed the partial back and ask it to continue seamlessly.
            messages.append({"role": "assistant", "content": chunk})
            messages.append({
                "role": "user",
                "content": (
                    "Continue the LaTeX EXACTLY from where you stopped — do NOT "
                    "repeat anything you already wrote, and do NOT restart the "
                    "preamble. Keep generating the remaining questions, then end "
                    "with \\end{document} followed by the <secret-rubrics>...</"
                    "secret-rubrics> JSON block. Output only the continuation."
                ),
            })

        raw_tex = self._sanitize_latex(full.strip())

        raw_tex = raw_tex.replace("{{EXAM_ID}}", exam_id)
        raw_tex = raw_tex.replace("{{USER_ID}}", user_id)
        raw_tex = raw_tex.replace("{{COURSE_ID}}", course_id)
        raw_tex = raw_tex.replace("{{UNIVERSITY}}", university)
        # Safety net: force the branded university name even if the model
        # ignored the instruction and emitted a placeholder/invented name.
        raw_tex = re.sub(
            r'University Name Placeholder|\[University Name\]|\{University Name\}|'
            r'<University Name>|Your University(?: Name)?|'
            r'Mudaris University of Technology',
            university,
            raw_tex,
        )

        return raw_tex.strip()

    @staticmethod
    def _sanitize_latex(raw_tex: str) -> str:
        """Strip markdown fences and conversational preamble/trailer around the LaTeX."""
        # Remove all markdown code fences (```latex, ```tex, ```) anywhere in the text
        raw_tex = re.sub(r'```(?:latex|tex)?', '', raw_tex)
        # Drop any conversational preamble before \documentclass
        doc_start = raw_tex.find('\\documentclass')
        if doc_start > 0:
            raw_tex = raw_tex[doc_start:]
        # Drop any trailing conversational text after the secret-rubrics block (if present)
        rubric_end = raw_tex.rfind('</secret-rubrics>')
        if rubric_end != -1:
            raw_tex = raw_tex[: rubric_end + len('</secret-rubrics>')]
        else:
            # Otherwise cut anything after the final \end{document}
            doc_end = raw_tex.rfind('\\end{document}')
            if doc_end != -1:
                raw_tex = raw_tex[: doc_end + len('\\end{document}')]
        raw_tex = raw_tex.strip()

        # Safety net: if the model's output was truncated before finishing,
        # close any dangling list environment and append \end{document} so the
        # PDF still compiles.
        if '\\end{document}' not in raw_tex:
            # Collapse any trailing run of underscore answer-lines that got cut off
            raw_tex = re.sub(r'(\\_[\s\\_]*)$', '', raw_tex).rstrip()
            if '\\begin{itemize}' in raw_tex and raw_tex.count('\\begin{itemize}') > raw_tex.count('\\end{itemize}'):
                raw_tex += '\n\\end{itemize}'
            if '\\begin{enumerate}' in raw_tex and raw_tex.count('\\begin{enumerate}') > raw_tex.count('\\end{enumerate}'):
                raw_tex += '\n\\end{enumerate}'
            raw_tex += '\n\\end{document}'

        # Robustness: LLMs frequently emit unescaped specials (e.g. stray `_`)
        # in text mode, which causes "Missing $ inserted" compile failures.
        # Load forgiving packages so common offenders still compile.
        raw_tex = ExamGeneratorAgent._inject_safety_packages(raw_tex)
        raw_tex = ExamGeneratorAgent._fix_overflowing_tables(raw_tex)
        raw_tex = ExamGeneratorAgent._fix_tabularx_without_x(raw_tex)
        raw_tex = ExamGeneratorAgent._fix_counter_itemize(raw_tex)
        return raw_tex.strip()

    @staticmethod
    def _fix_tabularx_without_x(tex: str) -> str:
        """Ensure every tabularx has an X column.

        tabularx stretches to its target width (e.g. \\textwidth) by widening its
        X columns. With no X column the surplus width is dumped into a spurious
        trailing empty cell — the "extra empty column" bug. LLMs often emit
        \\begin{tabularx}{\\textwidth}{|p{12cm}|c|} (fixed columns only). Promote
        the first wrappable text column (p/m/b{..} or l) to X — or, failing that,
        the first c/r — so the table fills the width cleanly with no phantom cell.
        This is brace-aware, so specs like p{12cm} are parsed correctly (the older
        regex-based _fix_overflowing_tables cannot match those).
        """
        def read_group(s: str, pos: int):
            """s[pos] must be '{'. Return (inner, index_after_closing_brace)."""
            if pos >= len(s) or s[pos] != '{':
                return None, pos
            depth, i = 0, pos
            while i < len(s):
                if s[i] == '{':
                    depth += 1
                elif s[i] == '}':
                    depth -= 1
                    if depth == 0:
                        return s[pos + 1:i], i + 1
                i += 1
            return None, pos

        def promote(spec: str) -> str:
            # First p{..}/m{..}/b{..} column → X (drop its width arg).
            m = re.search(r'[pmb]\{', spec)
            if m:
                _, after = read_group(spec, m.end() - 1)
                return spec[:m.start()] + 'X' + spec[after:]
            # else first bare l → X, else first c/r → X.
            for ch in ('l', 'c', 'r'):
                idx = spec.find(ch)
                if idx != -1:
                    return spec[:idx] + 'X' + spec[idx + 1:]
            return spec

        marker = '\\begin{tabularx}'
        out, i = [], 0
        while True:
            j = tex.find(marker, i)
            if j == -1:
                out.append(tex[i:])
                break
            out.append(tex[i:j])
            k = j + len(marker)
            width, k1 = read_group(tex, k)
            spec, k2 = read_group(tex, k1)
            if width is None or spec is None:
                out.append(marker)          # malformed; leave untouched
                i = k
                continue
            new_spec = spec if 'X' in spec else promote(spec)
            out.append(marker + '{' + width + '}{' + new_spec + '}')
            i = k2
        return ''.join(out)

    @staticmethod
    def _fix_counter_itemize(tex: str) -> str:
        """Convert itemize lists that use an enumerate-only counter label into
        enumerate.

        enumitem counter macros (\\Alph*, \\alph*, \\arabic*, \\roman*, \\Roman*)
        only have a counter to reference inside an \\begin{enumerate}. LLMs
        frequently emit MCQ options as \\begin{itemize}[label=\\Alph*.], which
        fails to compile with "Missing number, treated as zero" (\\Alph* expands
        to \\c@ of a counter that does not exist in itemize). Rewrite the opening
        tag and its matching \\end{itemize} to enumerate; lists are properly
        nested, so the most recent unmatched begin owns each end.
        """
        counter_re = re.compile(r'\\(?:Alph|alph|arabic|roman|Roman)\*')
        token_re = re.compile(
            r'\\begin\{(itemize|enumerate)\}(\[[^\]]*\])?'
            r'|\\end\{(itemize|enumerate)\}'
        )
        out: list[str] = []
        stack: list[bool] = []  # True if the matching begin was converted
        pos = 0
        for m in token_re.finditer(tex):
            out.append(tex[pos:m.start()])
            pos = m.end()
            begin_env = m.group(1)
            if begin_env:  # \begin{...}
                opts = m.group(2) or ''
                convert = begin_env == 'itemize' and bool(counter_re.search(opts))
                stack.append(convert)
                out.append('\\begin{enumerate}' + opts if convert else m.group(0))
            else:  # \end{...}
                converted = stack.pop() if stack else False
                out.append('\\end{enumerate}' if converted else m.group(0))
        out.append(tex[pos:])
        return ''.join(out)

    @staticmethod
    def _fix_overflowing_tables(tex: str) -> str:
        """Stop wide tables from running off the right edge of the page.

        A \\begin{tabularx}{...}{spec} with NO 'X' column cannot wrap — its 'l'
        columns set long text on one line and overflow the page (this is the
        'right column out of the page' bug). When that happens, convert the
        non-numeric 'l' columns to 'X' so the text wraps and the table fits.
        """
        def fix_spec(match: "re.Match") -> str:
            width_grp = match.group(1)   # e.g. \textwidth
            spec = match.group(2)        # e.g. |c|l|c|l|
            # Only act on specs with no wrapping column already present.
            if 'X' in spec or 'p{' in spec or 'm{' in spec or 'b{' in spec:
                return match.group(0)
            if 'l' not in spec:
                return match.group(0)
            # Convert long-text 'l' columns to wrapping 'X'; leave 'c'/'r' (used
            # for short number/letter cells) alone.
            new_spec = spec.replace('l', 'X')
            return '\\begin{tabularx}{' + width_grp + '}{' + new_spec + '}'

        # Column spec for the broken case has no nested braces, so [^{}]* is safe.
        return re.sub(
            r'\\begin\{tabularx\}\{([^}]*)\}\{([^{}]*)\}',
            fix_spec,
            tex,
        )

    @staticmethod
    def _inject_safety_packages(tex: str) -> str:
        """Insert packages that make stray special characters compile cleanly,
        plus a 'Mudaris' mark in the bottom-left of every page.
        Safety packages and the mark are injected independently so older
        exams (that already have the safety packages) still get the mark."""
        m = re.search(r'(\\documentclass[^\n]*\n)', tex)
        if not m:
            return tex
        insert_at = m.end()

        additions = ""
        if '\\usepackage{underscore}' not in tex:
            additions += (
                "\\usepackage{underscore}   % allow raw _ in text\n"
                "\\usepackage[T1]{fontenc}\n"
                "\\usepackage{textcomp}     % <, >, and other text symbols\n"
            )
        # Math + code packages so equation/code questions compile even if the
        # model forgot to include them.
        if '\\usepackage{amsmath}' not in tex and '\\usepackage{amsmath,amssymb}' not in tex:
            additions += "\\usepackage{amsmath,amssymb}\n"
        if '\\usepackage{verbatim}' not in tex:
            additions += "\\usepackage{verbatim}\n"
        if '\\usepackage{eso-pic}' not in tex and '\\AddToShipoutPictureFG' not in tex:
            additions += (
                "\\usepackage{eso-pic}\n"
                "\\usepackage{xcolor}\n"
                "\\AddToShipoutPictureFG{\\AtPageLowerLeft{\\put(28,20){\\textcolor{gray}{\\small Mudaris}}}}\n"
            )
        # Keep questions consistently aligned at the left margin: kill stray
        # paragraph indentation, and stop list labels from overhanging into the
        # left margin (the main cause of "some questions sit further left").
        if '\\setlength{\\parindent}{0pt}' not in tex:
            additions += "\\setlength{\\parindent}{0pt}\n"
        if '\\usepackage{enumitem}' not in tex:
            additions += "\\usepackage{enumitem}\n"
        if not additions:
            return tex
        return tex[:insert_at] + additions + tex[insert_at:]

    def extract_and_save_exam_metadata(self, tex_content: str, exam_id: str, user_id: str, course_id: str) -> dict:
        logger.info("Extracting and parsing secret rubric metadata from generated PDF source...")
        
        # Regex to locate <secret-rubrics>...</secret-rubrics>
        pattern = r'<secret-rubrics>(.*?)</secret-rubrics>'
        match = re.search(pattern, tex_content, re.DOTALL)
        
        if not match:
            logger.warning("No secret-rubrics block found in the generated PDF source.")
            return {"cleaned_tex": tex_content, "rubrics": {}}

        try:
            rubric_json_str = match.group(1).strip()
            rubric_data = json.loads(rubric_json_str)
            
            # Clean up the LaTeX: Delete the secret-rubrics block completely
            cleaned_tex = re.sub(pattern, "", tex_content, flags=re.DOTALL)
            
            logger.info(f"Successfully extracted rubric metadata for Exam {exam_id}.")
            return {"cleaned_tex": cleaned_tex, "rubrics": rubric_data}

        except Exception as e:
            logger.error(f"Failed to extract metadata: {str(e)}")
            return {"cleaned_tex": tex_content, "rubrics": {}}

    @staticmethod
    def _tutorial_brief(tutorial_insights: list = None, tutorial_texts: list = None,
                        max_problems: int = 10) -> str:
        """Compact text block describing tutorial practice problems (topics +
        problem ideas + methods) — shared by summary/flashcard generation."""
        parts = []
        for t in (tutorial_insights or []):
            topics_str = _join_texts(t.get("topics"), ", ", 15)
            block = f"Topics practiced: {topics_str}" if topics_str else ""
            lines = []
            for p in t.get("problems", [])[:max_problems]:
                concept = (p.get("concept") or "").strip()
                statement = (p.get("statement") or "").strip()
                method = (p.get("method") or "").strip()
                line = "• " + (f"{concept}: " if concept else "") + statement
                if method:
                    line += f" (method: {method})"
                lines.append(line.strip())
            if lines:
                block += "\nPractice problems & how to solve them:\n" + "\n".join(lines)
            elif t.get("workedExamples"):
                block += "\nExercises: " + _join_texts(t.get("workedExamples"), ", ", 8)
            if block.strip():
                parts.append(block)
        if tutorial_texts:
            combined = "\n\n---\n\n".join([x[:2500] for x in tutorial_texts[:2]])
            if combined.strip():
                parts.append("Raw tutorial problems:\n" + combined[:6000])
        return "\n\n".join(parts)

    def generate_summary(self, academic_data: dict, topics: list,
                         document_insights: list = None, audio_insights: list = None,
                         historical_analysis: list = None, document_texts: list = None,
                         historical_texts: list = None,
                         tutorial_insights: list = None, tutorial_texts: list = None,
                         instructions: str = "") -> dict:
        """Generate a structured study summary from the course intelligence.
        Returns {title, overview, sections[], keyTerms[], examFocus[]}."""
        logger.info("Generating study summary from course intelligence...")

        sections = []
        if document_texts:
            combined = "\n\n---\n\n".join([t[:4000] for t in document_texts[:4]])
            sections.append(f"--- LECTURE CONTENT (primary source) ---\n{combined[:14000]}")
        if document_insights:
            parts = []
            for doc in document_insights:
                topics_str = _join_texts(doc.get("topics"), ", ", 20)
                defs = doc.get("definitions", [])[:15]
                defs_str = "; ".join([f"{d['term']}: {d['definition']}" for d in defs if 'term' in d])
                formulas_str = _join_texts(doc.get("formulas"), ", ", 10)
                parts.append(f"Topics: {topics_str}\nDefinitions: {defs_str}\nFormulas: {formulas_str}")
            sections.append("--- DOCUMENT ANALYSIS ---\n" + "\n\n".join(parts))
        if audio_insights:
            parts = []
            for a in audio_insights:
                emph = a.get("keyEmphasis", [])[:10]
                emph_str = "\n".join([f"- [{e.get('emphasisLevel','low')}] {e.get('topic','')}" for e in emph])
                summ = a.get("summary", "")
                block = (f"Lecture summary: {summ}\n" if summ else "") + (f"Professor emphasis:\n{emph_str}" if emph_str else "")
                if block:
                    parts.append(block)
            if parts:
                sections.append("--- AUDIO INSIGHTS ---\n" + "\n\n".join(parts))
        if historical_analysis:
            parts = []
            for h in historical_analysis:
                weights = h.get("topicWeights", [])[:15]
                weights_str = "\n".join([f"- {w.get('topic','')}: {w.get('weight',0):.0%}" for w in weights])
                parts.append(f"Exam topic weights (prioritize these):\n{weights_str}")
            sections.append("--- HISTORICAL EXAM PATTERNS ---\n" + "\n\n".join(parts))
        # The actual past-exam questions: richest source of the specific concepts
        # the student will be tested on. Make a detailed section covering each.
        if historical_texts:
            combined_hist = "\n\n---\n\n".join([t[:5000] for t in historical_texts[:2]])
            if combined_hist.strip():
                sections.append(
                    "--- PAST EXAM QUESTIONS (cover EVERY concept these questions test, in "
                    "depth — explain the topic behind each question and how to answer it) ---\n"
                    + combined_hist[:12000]
                )

        tut_brief = self._tutorial_brief(tutorial_insights, tutorial_texts)
        if tut_brief:
            sections.append(
                "--- TUTORIALS (practice problems — cover their topics and the METHOD "
                "for solving each problem type; these problem types often appear on exams) ---\n"
                + tut_brief
            )

        topics_line = ", ".join(topics) if topics else "All key topics"
        custom_block = ""
        exclusion_reminder = ""
        if (instructions or "").strip():
            custom_block = (
                "=== USER'S CUSTOM INSTRUCTIONS (HIGHEST PRIORITY — follow these EXACTLY; "
                "they OVERRIDE every default rule below where they conflict) ===\n"
                f"{instructions.strip()}\n"
                "If these instructions EXCLUDE/omit/skip a topic, that topic must NOT appear "
                "anywhere in the output (no section, heading, keyPoint, keyTerm, or examFocus) "
                "even though the guidance below says to cover everything.\n"
                "(Still return the same JSON schema.)\n\n"
            )
            exclusion_reminder = (
                "\n- REMINDER: obey the user's custom instructions above. If they asked to "
                "EXCLUDE a topic, leave it out ENTIRELY — do NOT create a section, keyPoint, "
                "keyTerm, or examFocus for it, even though it appears in the materials/past exams."
            )
        user_payload = (
            custom_block
            + f"Target topics: {topics_line}\n"
            f"Write a DETAILED, comprehensive study summary from the materials below — this is "
            f"a full revision document, so be thorough, not brief.\n"
            f"- Make a SEPARATE, in-depth section for every major topic (aim for 8-15 sections "
            f"when the material supports it); each section must actually teach the concept "
            f"with its definitions and formulas.\n"
            f"- Cover EVERY topic, concept, and question type that appears in the PAST EXAMS in "
            f"depth — these are the most important. Pull out the specific concepts the past "
            f"exams test and explain them fully.\n"
            f"- For EVERY tutorial practice problem, explain the underlying concept AND the "
            f"step-by-step method/formula for solving that problem type (these reappear on exams).\n"
            f"- Produce a long, comprehensive keyTerms list (aim for 20-40 terms) drawn from the "
            f"lectures, past exams, and tutorials."
            + exclusion_reminder
            + "\n\n"
            + "\n\n".join(sections)
        )

        from src.utils.json_parse import extract_json_object
        response = chat_with_retry(
            self.client,
            model=self.model_id,
            messages=[
                {"role": "system", "content": prompts.SUMMARY_GEN_SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.3,
            max_tokens=max(settings.OPENROUTER_MAX_TOKENS, 20000),
        )

        raw = (response.choices[0].message.content or "").strip()
        try:
            data = extract_json_object(raw)
            sections = []
            for s in data.get("sections", []):
                sections.append({
                    "heading": s.get("heading", ""),
                    "content": s.get("content", ""),
                    "keyPoints": s.get("keyPoints", []),
                    "examLikelihood": s.get("examLikelihood", "medium"),
                    "examWeight": s.get("examWeight", 0),
                })
            return {
                "title": data.get("title", "Study Summary"),
                "overview": data.get("overview", ""),
                "sections": sections,
                "keyTerms": data.get("keyTerms", []),
                "examFocus": data.get("examFocus", []),
            }
        except Exception as ex:
            logger.error(f"Failed to parse summary JSON: {ex}")
            return {}

    def generate_flashcards(self, academic_data: dict, topics: list,
                            document_insights: list = None, audio_insights: list = None,
                            historical_analysis: list = None, document_texts: list = None,
                            historical_texts: list = None, count: int = 20,
                            tutorial_insights: list = None, tutorial_texts: list = None) -> list:
        """Generate study flashcards from the course intelligence. Returns a list
        of {front, back, topic} dicts, prioritizing exam-likely content."""
        logger.info("Generating flashcards from course intelligence...")

        sections = []

        # 1) Strongest exam signal first: actual past-exam questions
        if historical_texts:
            combined_hist = "\n\n---\n\n".join([t[:5000] for t in historical_texts[:2]])
            sections.append(
                "--- PAST EXAM QUESTIONS (HIGHEST PRIORITY — turn these into flashcards) ---\n"
                + combined_hist[:10000]
            )
        if historical_analysis:
            parts = []
            for h in historical_analysis:
                weights = h.get("topicWeights", [])[:15]
                weights_str = "\n".join([f"- {w.get('topic','')}: {w.get('weight',0):.0%} ({w.get('questionCount',0)} Qs)" for w in weights])
                qtypes = h.get("questionTypes", [])[:5]
                qtypes_str = ", ".join([f"{q.get('type','')}: {q.get('percentage',0):.0f}%" for q in qtypes])
                parts.append(f"Topic weights (how often each appears on exams):\n{weights_str}\nQuestion types: {qtypes_str}")
            sections.append("--- HISTORICAL EXAM PATTERNS ---\n" + "\n\n".join(parts))

        # 2) Professor's explicit exam hints + emphasis from recordings
        if audio_insights:
            parts = []
            for a in audio_insights:
                hints = a.get("examHints", [])[:10]
                hints_str = "\n".join([f"- [{h.get('confidence',0):.0%}] {h.get('hint','')}" for h in hints])
                emph = a.get("keyEmphasis", [])[:10]
                emph_str = "\n".join([f"- [{e.get('emphasisLevel','low')}] {e.get('topic','')}" for e in emph])
                block = ""
                if hints_str:
                    block += f"Professor exam hints:\n{hints_str}\n"
                if emph_str:
                    block += f"Professor emphasis:\n{emph_str}"
                if block:
                    parts.append(block)
            if parts:
                sections.append("--- AUDIO INSIGHTS (professor signalled these for the exam) ---\n" + "\n\n".join(parts))

        # 3) Supporting source material from the lecture documents
        if document_insights:
            parts = []
            for doc in document_insights:
                topics_str = _join_texts(doc.get("topics"), ", ", 20)
                defs = doc.get("definitions", [])[:15]
                defs_str = "; ".join([f"{d['term']}: {d['definition']}" for d in defs if 'term' in d])
                formulas_str = _join_texts(doc.get("formulas"), ", ", 10)
                parts.append(f"Topics: {topics_str}\nDefinitions: {defs_str}\nFormulas: {formulas_str}")
            sections.append("--- DOCUMENT ANALYSIS ---\n" + "\n\n".join(parts))
        if document_texts:
            combined = "\n\n---\n\n".join([t[:3000] for t in document_texts[:3]])
            sections.append(f"--- LECTURE CONTENT ---\n{combined[:9000]}")

        # 4) Tutorials — practice problems: make cards on how to solve each type.
        tut_brief = self._tutorial_brief(tutorial_insights, tutorial_texts)
        if tut_brief:
            sections.append(
                "--- TUTORIALS (practice problems — make cards that test how to solve "
                "these problem TYPES and which method/formula to use) ---\n" + tut_brief
            )

        topics_line = ", ".join(topics) if topics else "All key topics"
        user_payload = (
            f"Target topics: {topics_line}\n"
            f"Create about {count} flashcards from the materials below.\n"
            f"PRIORITIZE content that the past exams asked about and that the professor "
            f"flagged for the exam — those cards are most valuable. Weight the number of "
            f"cards per topic by how heavily it appears in the past exams. Also include "
            f"cards on how to solve the problem types shown in the tutorials.\n\n"
            + "\n\n".join(sections)
        )

        from src.utils.json_parse import extract_json_object
        response = chat_with_retry(
            self.client,
            model=self.model_id,
            messages=[
                {"role": "system", "content": prompts.FLASHCARD_GEN_SYSTEM_PROMPT},
                {"role": "user", "content": user_payload},
            ],
            temperature=0.3,
            max_tokens=max(settings.OPENROUTER_MAX_TOKENS, 20000),
        )

        raw = (response.choices[0].message.content or "").strip()
        try:
            data = extract_json_object(raw)
            cards = data.get("cards", [])
            # Keep only well-formed cards
            return [
                {
                    "front": c.get("front", ""),
                    "back": c.get("back", ""),
                    "topic": c.get("topic", ""),
                    "examLikelihood": c.get("examLikelihood", "medium"),
                }
                for c in cards if c.get("front") and c.get("back")
            ]
        except Exception as e:
            logger.error(f"Failed to parse flashcards JSON: {e}")
            return []

    def grade_document_submission(self, questions_rubrics: dict, exam_text: str,
                                  submission_text: str = None,
                                  image_data_uris: list = None) -> dict:
        """Grade a student's uploaded solved exam (typed text OR handwritten images)
        against the rubric. Returns a {q_id: {score, feedback}} dict — the caller
        applies max_scores and totals."""
        logger.info("Grading uploaded exam submission...")

        key_lines = []
        for qid, r in sorted(questions_rubrics.items()):
            qtype = r.get("question_type", "written")
            maxs = r.get("max_score", 5 if qtype in ("mcq", "true_false") else 15)
            if qtype in ("mcq", "true_false"):
                key_lines.append(
                    f"{qid} ({qtype}, max {maxs} marks): correct answer = "
                    f"{r.get('correct_answer','')}. {r.get('explanation','')}"
                )
            else:
                key_lines.append(
                    f"{qid} ({qtype}, max {maxs} marks): full-mark criteria = {r.get('criteria','')}"
                )
        key_str = "\n".join(key_lines)

        instructions = f"""You are an exam grader. A student has submitted their completed exam (it may be TYPED or HANDWRITTEN).

EXAM QUESTIONS (for reference):
{exam_text[:8000]}

ANSWER KEY / RUBRIC:
{key_str}

The submission may contain ANY form of answer — prose, DIAGRAMS, CODE, or MATHEMATICAL
equations/derivations. Interpret all of them:
- Diagrams (flowcharts, UML, ER, graphs, sketches): judge whether the diagram is correct and complete for what the question asks.
- Code: judge correctness and logic — does it solve the problem? Minor syntax slips are fine if the intent is clear.
- Math equations / derivations: check the steps and the final result.

TASK: Read the student's submission, locate their answer to EACH question (q1, q2, ...),
and grade it. Judge correctness YOURSELF from the exam question and the subject matter —
the answer key is only a hint and may be imperfect, so never penalize an answer that is
actually correct.
- MCQ / true-false: work out the correct option from the question itself; full marks if the student's answer is correct, otherwise 0.
- Written / diagram / code / math: award partial marks out of the max based on correctness and how well it meets the criteria; give credit for correct diagrams, working code, and valid derivations.
- If a question has no answer in the submission, score 0 and set student_answer to "No answer found".

For EVERY question return THREE things so the student can compare and learn:
1. "student_answer": EXACTLY what the student wrote, transcribed faithfully. For MCQ/true-false give their chosen option (e.g. "B" / "TRUE"). For handwriting, diagrams, code, or math, transcribe/describe what they actually put.
2. "model_answer": the FULL correct (model) answer to the question — the complete worked answer, not just a letter. For MCQ/true-false, give the correct option AND a one-line reason. For calculation/derivation, show the key steps and final result. For code/diagram, describe the correct solution.
3. "feedback": a short note on WHERE the student's answer differs from the model answer / where they lost marks (empty string if fully correct).

Respond ONLY with raw JSON (no markdown, no commentary):
{{"results": {{"q1": {{"score": <number>, "student_answer": "...", "model_answer": "...", "feedback": "..."}}, "q2": {{...}}}}}}"""

        content = [{"type": "text", "text": instructions}]
        if submission_text:
            content.append({
                "type": "text",
                "text": f"\n--- STUDENT SUBMISSION (typed) ---\n{submission_text[:15000]}",
            })
        if image_data_uris:
            content.append({"type": "text", "text": "\n--- STUDENT SUBMISSION (handwritten images below) ---"})
            for uri in image_data_uris[:5]:
                content.append({"type": "image_url", "image_url": {"url": uri}})

        from src.utils.json_parse import extract_json_object
        response = chat_with_retry(
            self.client,
            model=self.model_id,
            messages=[{"role": "user", "content": content}],
            temperature=0.1,
            # Model answers for every question can be long; give plenty of room.
            max_tokens=max(settings.OPENROUTER_MAX_TOKENS, 12000),
        )
        raw = (response.choices[0].message.content or "").strip()
        try:
            return extract_json_object(raw).get("results", {})
        except Exception as ex:
            logger.error(f"Failed to parse submission grade JSON: {ex}")
            return {}

    def repair_latex(self, tex_content: str, error_hint: str = "") -> str:
        """Ask the model to fix a LaTeX document that fails to compile.
        Returns repaired, sanitized LaTeX (preserving any <secret-rubrics> block)."""
        logger.info("Repairing LaTeX that failed to compile...")
        # Separate the secret-rubrics block so the model only fixes the document
        rubrics_block = ""
        m = re.search(r'<secret-rubrics>.*?</secret-rubrics>', tex_content, re.DOTALL)
        if m:
            rubrics_block = m.group(0)
            doc_only = tex_content.replace(rubrics_block, "").strip()
        else:
            doc_only = tex_content

        prompt = f"""The following LaTeX document fails to compile with pdflatex.
{('Compiler error: ' + error_hint) if error_hint else ''}

Fix ALL syntax errors so it compiles cleanly with pdflatex:
- Escape stray special characters in text: _ & # % -> \\_ \\& \\# \\%
- Balance all braces {{}} and \\begin/\\end environments
- Put math symbols (^, _, <, >, etc.) inside $...$
- Keep the content and structure the same; do NOT add commentary

Return ONLY the corrected, complete LaTeX document (from \\documentclass to \\end{{document}}). No markdown fences.

[LATEX TO FIX]
{doc_only[:25000]}"""

        try:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=16000,
            )
            fixed = self._sanitize_latex((response.choices[0].message.content or "").strip())
            if rubrics_block and '<secret-rubrics>' not in fixed:
                fixed = fixed + "\n" + rubrics_block
            return fixed
        except Exception as e:
            logger.error(f"LaTeX repair failed: {e}")
            return tex_content

    def generate_rubrics_from_tex(self, tex_content: str, exam_id: str) -> dict:
        """Fallback: derive grading rubrics (question types + answer keys) by
        reading the already-generated exam LaTeX. Used when the inline
        <secret-rubrics> block is missing (e.g. the generation was truncated)."""
        logger.info(f"Deriving rubrics from exam text for {exam_id} (fallback)...")
        prompt = f"""You are an exam answer-key generator. Read the following LaTeX exam and produce the grading rubric.

For EACH question in the exam, in order, output an entry keyed q1, q2, q3, ...
- For multiple-choice questions: {{"question_type": "mcq", "correct_answer": "A|B|C|D", "max_score": <marks>, "explanation": "short reason"}}
- For true/false questions: {{"question_type": "true_false", "correct_answer": "TRUE|FALSE", "max_score": <marks>, "explanation": "short reason"}}
- For written/essay/fill-blank questions: {{"question_type": "written", "max_score": <marks>, "criteria": "what a full-mark answer must contain"}}

Respond ONLY with raw JSON (no markdown, no commentary) in this exact shape:
{{"exam_id": "{exam_id}", "questions": {{"q1": {{...}}, "q2": {{...}}}}}}

[EXAM LATEX]
{tex_content[:20000]}"""

        from src.utils.json_parse import extract_json_object
        try:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=max(settings.OPENROUTER_MAX_TOKENS, 20000),
            )
            # Robust parse (handles fences, trailing commas, and truncation).
            return extract_json_object(response.choices[0].message.content or "")
        except Exception as e:
            logger.error(f"Rubric fallback generation failed: {e}")
            return {}

    # Known-good preamble we wrap the model's answer-key BODY in, so the document
    # structure can never be malformed (the model only writes the per-question body).
    _ANSWER_KEY_PREAMBLE = (
        "\\documentclass[11pt,a4paper]{article}\n"
        "\\usepackage[a4paper,margin=2.2cm]{geometry}\n"
        "\\usepackage{amsmath,amssymb}\n"
        "\\usepackage{verbatim}\n"
        "\\usepackage{xcolor}\n"
        "\\usepackage{parskip}\n"
    )

    def generate_answer_key(self, exam_tex: str, exam_id: str) -> str:
        """Produce a COMPLETE model-answer (worked solutions) LaTeX document for an
        already-generated exam. The model writes ONLY the body (per-question
        content); we wrap it in a guaranteed-valid document skeleton so the
        structure is never malformed. Continues generation if the model is cut off
        by the token limit. Returns sanitized, watermarked LaTeX ready to compile."""
        logger.info(f"Generating model-answer key for exam {exam_id}...")

        # Drop any leftover secret-rubrics block from the exam source.
        clean_exam = re.sub(r'<secret-rubrics>.*?</secret-rubrics>', '', exam_tex, flags=re.DOTALL).strip()

        system = (
            "You are an expert examiner writing the OFFICIAL MODEL ANSWER KEY for a "
            "university exam, given the exam as LaTeX.\n\n"
            "OUTPUT ONLY THE BODY CONTENT — the LaTeX that goes BETWEEN \\begin{document} "
            "and \\end{document}. Do NOT output \\documentclass, \\usepackage, "
            "\\begin{document}, \\end{document}, or any document title — those are added "
            "for you. Do NOT use markdown (no **bold**, no ``` fences); use LaTeX only.\n\n"
            "For EVERY question in the exam, in order:\n"
            "1. Type the FULL question as a black bold heading: \\textbf{Question N.} followed "
            "by the complete question text (and, for MCQs, all of its options).\n"
            "2. Then the ANSWER in RED, laid out cleanly. STATE THE EXACT ANSWER FIRST on its own "
            "line, then a short explanation underneath. Do NOT write the word 'Why'.\n"
            "   Use exactly this shape:\n"
            "   {\\color{red}\\textbf{Answer:} <the exact answer>}\\par\\smallskip\n"
            "   {\\color{red}<short, clear explanation or working>}\n"
            "   - MCQ / true-false: the exact correct option first (e.g. 'B'), then a one-line reason.\n"
            "   - Calculation / derivation: the FINAL result first (e.g. 'CPI = 1.6'), then clean steps "
            "(use $...$ or \\[ \\]).\n"
            "   - Code / assembly questions (e.g. 'write MIPS for ...'): the ANSWER IS THE ACTUAL CODE "
            "in that language — put the real code in a \\begin{verbatim}...\\end{verbatim} block, then a "
            "short note. Do NOT just describe what to do; write the code itself.\n"
            "   - Diagram: state what the correct diagram is, then its key labels.\n"
            "   - Written/essay: the key answer/conclusion first, then the supporting points.\n\n"
            "Separate each question from the next with \\bigskip. Answer ALL questions — never stop early."
        )
        user = f"Answer EVERY question in this exam.\n\n--- EXAM (LaTeX) ---\n{clean_exam[:18000]}"

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        full = ""
        # Large per-call budget (Gemini Pro supports it) so most exams finish in
        # one call; keep continuing if the model is still cut off.
        MAX_CONTINUATIONS = 4
        for attempt in range(MAX_CONTINUATIONS + 1):
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=messages,
                temperature=0.2,
                max_tokens=16000,
            )
            choice = response.choices[0]
            chunk = (choice.message.content or "")
            full += chunk
            finish = getattr(choice, "finish_reason", None)
            if finish != "length":
                break
            if attempt == MAX_CONTINUATIONS:
                logger.warning(f"Answer key {exam_id}: hit continuation cap.")
                break
            logger.info(f"Answer key {exam_id}: truncated (finish={finish}); continuing.")
            messages.append({"role": "assistant", "content": chunk})
            messages.append({
                "role": "user",
                "content": (
                    "Continue EXACTLY from where you stopped — do not repeat anything. "
                    "Keep writing the remaining answers in the same format. Output only the "
                    "continuation (no preamble, no \\end{document})."
                ),
            })

        body = full.strip()
        # Strip anything that would clash with our skeleton or break compilation.
        body = re.sub(r'```(?:latex|tex)?', '', body).replace('```', '')
        body = re.sub(r'\\documentclass.*?\\begin\{document\}', '', body, flags=re.DOTALL)
        body = body.replace('\\begin{document}', '').replace('\\end{document}', '')
        # Convert stray markdown bold to LaTeX (the model sometimes slips).
        body = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', body)
        body = body.strip()

        doc = (
            self._ANSWER_KEY_PREAMBLE
            + "\\begin{document}\n"
            + "\\begin{center}{\\LARGE\\bfseries Model Answers}\\end{center}\n\\vspace{0.6em}\n"
            + body
            + "\n\\end{document}\n"
        )
        return self._sanitize_latex(doc)

    def generate_answer_pairs(self, exam_tex: str, exam_id: str) -> list:
        """Reliable answer data: ask the model for the full question text + the
        full answer as PLAIN TEXT JSON, so we can render a guaranteed-compilable
        PDF ourselves. Retries on bad JSON. Returns [{question, answer}, ...]."""
        from src.utils.json_parse import parse_with_retry

        clean_exam = re.sub(r'<secret-rubrics>.*?</secret-rubrics>', '', exam_tex, flags=re.DOTALL).strip()
        system = (
            "You produce OFFICIAL MODEL ANSWERS for an exam. Reply with ONE JSON object "
            "and NOTHING else — begin with { and end with }.\n"
            'Schema: {"items": [{"question": "<full question text, incl. options for MCQ>", '
            '"answer": "<the EXACT answer only>", "explanation": "<brief reasoning>"}, ...]}\n'
            "Include EVERY question in the exam, in order — do not skip any.\n\n"
            "FIELDS:\n"
            "- \"answer\": ONLY the exact answer itself — no preamble, no 'Why'.\n"
            "    * MCQ / true-false: just the correct option, e.g. 'B' or 'True'.\n"
            "    * Calculation: just the final result, e.g. 'CPI = 1.6'.\n"
            "    * Code / assembly (e.g. 'write MIPS ...'): the ACTUAL CODE in that language, "
            "written line by line (preserve real line breaks). The code IS the answer — do not "
            "describe what to do.\n"
            "    * Written/short: the key answer/conclusion in 1-2 lines.\n"
            "- \"explanation\": a short, clear reason or working that justifies the answer. "
            "Do NOT start it with the word 'Why'. Leave it \"\" if the answer is self-evident.\n\n"
            "PLAIN TEXT only: no markdown, no LaTeX commands. Normal symbols like $ (e.g. $t0) are fine. "
            "For code answers, put each instruction on its own line."
        )

        def _call(reminder: str) -> str:
            response = chat_with_retry(
                self.client,
                model=self.model_id,
                messages=[
                    {"role": "system", "content": system + reminder},
                    {"role": "user", "content": f"--- EXAM ---\n{clean_exam[:16000]}"},
                ],
                temperature=0.1,
                # Big budget so even long exams (many questions) fit in one JSON
                # object without truncation (Gemini Pro supports large output).
                max_tokens=16000,
            )
            return (response.choices[0].message.content or "").strip()

        try:
            data = parse_with_retry(_call, required_keys=("items",), label="answer key")
            items = data.get("items", []) or []
            return [
                {
                    "question": str(it.get("question", "")),
                    "answer": str(it.get("answer", "")),
                    "explanation": str(it.get("explanation", "")),
                }
                for it in items if isinstance(it, dict) and (it.get("question") or it.get("answer"))
            ]
        except Exception as e:
            logger.error(f"Answer-pairs generation failed for {exam_id}: {e}")
            return []

    @staticmethod
    def _answers_to_latex(items: list, exam_id: str) -> str:
        """Render {question, answer, explanation} items into a SAFE, always-compilable,
        cleanly-formatted answer key — question heading, the exact answer in red,
        then a short explanation, with a thin separator between questions. Multi-line
        answers (code/assembly) are shown monospaced with their line breaks kept."""
        def esc(s) -> str:
            repl = {
                "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
                "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
                "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
            }
            return "".join(repl.get(ch, ch) for ch in str(s or ""))

        def inline(s) -> str:
            # Single flowing paragraph (collapse newlines to spaces).
            return esc(str(s or "").replace("\r\n", " ").replace("\n", " ").strip())

        def block(s) -> str:
            # Preserve line breaks (for code/steps); monospace if multi-line.
            txt = str(s or "").replace("\r\n", "\n").strip()
            if not txt:
                return ""
            lines = [ln for ln in txt.split("\n") if ln.strip() != ""]
            if len(lines) <= 1:
                return esc(txt)
            joined = " \\\\\n".join(esc(ln) for ln in lines)
            return r"\ttfamily " + joined

        parts = [
            r"\documentclass[11pt,a4paper]{article}",
            r"\usepackage[a4paper,margin=2.3cm]{geometry}",
            r"\usepackage[T1]{fontenc}",
            r"\usepackage{textcomp}",
            r"\usepackage{parskip}",
            r"\usepackage{xcolor}",
            r"\definecolor{ansred}{HTML}{C8472F}",
            r"\usepackage{eso-pic}",
            r"\AddToShipoutPictureFG{\AtPageLowerLeft{\put(28,20){\textcolor{gray}{\small Mudaris}}}}",
            r"\setlength{\parindent}{0pt}",
            r"\begin{document}",
            r"\begin{center}{\LARGE\bfseries Model Answers}\end{center}",
            r"\vspace{1em}",
        ]
        n = len(items)
        for i, it in enumerate(items, 1):
            ans = block(it.get("answer", ""))
            expl = inline(it.get("explanation", ""))
            parts.append(r"\textbf{\large Question " + str(i) + r"}\par\smallskip")
            parts.append(inline(it.get("question", "")) + r"\par\smallskip")
            parts.append(r"\begin{flushleft}{\color{ansred}\textbf{Answer:}~ " + ans + r"}\end{flushleft}")
            if expl:
                parts.append(r"{\color{ansred}" + expl + r"}\par")
            parts.append(r"\vspace{0.6em}")
            if i < n:
                parts.append(r"{\color{gray}\rule{\linewidth}{0.3pt}}\par\vspace{0.9em}")
        parts.append(r"\end{document}")
        return "\n".join(parts)