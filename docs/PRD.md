# Mudaris — مُدرّس · Product Requirements Document (Build Spec)

> **Type:** Personal build spec / engineering roadmap
> **Owner:** Khalid (solo builder)
> **Status:** Living document — update as scope changes
> **Last updated:** 2026-07-15
> **Repo:** https://github.com/Conqyy/MudarisKH (private)

---

## 1. Product summary

**Mudaris (مُدرّس, "tutor")** is a bilingual (Arabic / English) AI study platform for Saudi university students. A student creates a **course**, uploads that course's real materials — lecture documents, audio/video recordings (or YouTube links), past exams, and tutorial problem sheets — and Mudaris turns them into exam-ready study output:

- **Practice exams** that mirror the *real* past exam's format, question types, and mark distribution, rendered as a LaTeX → PDF with a separate red model-answer key.
- **Chapter-ordered summaries** with a per-topic **exam-likelihood %** derived from real past-exam weights.
- **Flashcards** generated from the student's own materials.
- **An AI chat tutor** grounded *only* in the student's uploaded materials (no open-web hallucination).

The core differentiator is **fidelity to the student's actual course**: everything is scoped to the materials they uploaded, and exam generation is constrained to topics that appear in the *current* course's lecture documents — not generic subject knowledge.

### One-line pitch
> Upload your course, get a practice exam that looks like your professor's real exam — plus summaries, flashcards, and a tutor that only knows your material.

---

## 2. Goals & non-goals

### 2.1 Goals (what this product is)
1. **Faithful exam mirroring** — generated exams match the real past exam's structure (sections, question types, marks per question, total marks) as closely as possible.
2. **Current-course scoping** — never test topics that aren't in the current course's lecture documents, even if the past exam covered them.
3. **Grounded outputs** — summaries, flashcards, and tutor answers derive only from uploaded materials; no fabricated facts.
4. **Bilingual by design** — Arabic RTL and English handled correctly in UI *and* generated PDFs; professor quotes preserved verbatim in Arabic.
5. **Low-friction workflow** — upload → generate → study, with minimal configuration.
6. **Public availability** — deployable, multi-user, secure per-user data isolation.

### 2.2 Non-goals (explicitly out of scope, for now)
- Not a general-purpose chatbot or open-web tutor.
- Not an LMS / grade book / institutional integration (Blackboard, Moodle, etc.).
- Not a collaboration / classroom-sharing tool (single-student workspaces only).
- Not a live proctoring or timed-exam-taking platform (practice exams are for self-study).
- No mobile-native app in this phase (responsive web only).
- No payment/subscription billing in this phase.

---

## 3. Target users & personas

| Persona | Description | Primary need |
|---|---|---|
| **The exam-crammer** | Undergrad days before a final; has slides + a past exam. | A realistic practice exam + a likelihood-ranked summary of what to focus on. |
| **The lecture-misser** | Missed classes; has recordings or a YouTube playlist. | Audio → structured English notes with verbatim professor quotes. |
| **The steady studier** | Reviews weekly; wants flashcards + a tutor for questions. | Flashcards + grounded Q&A across the semester's materials. |

**Common context:** Saudi university, courses taught in a mix of Arabic and English, materials are a messy blend of both languages, and the *real past exam* is the single most trusted signal of what matters.

---

## 4. Core concepts / domain model

- **Course** — the top-level container a student creates. Owns everything below it.
- **Lecture document** — uploaded PDF/PPTX/DOCX course material. Defines the **current course scope**.
- **Audio recording** — uploaded audio/video file or YouTube link; transcribed and analyzed.
- **Historical (past) exam** — a real past exam (PDF or photo). The template Mudaris mirrors.
- **Tutorial** — a problem sheet; source of practice-style questions.
- **Generated exam** — a Mudaris-produced practice exam (PDF + answer-key PDF).
- **Summary** — chapter-ordered notes with exam-likelihood %.
- **Flashcard set** — Q/A cards generated from materials.
- **Intelligence** — the analyzed topic/weight model derived from past exams, scoped to current docs.
- **Schedule entry** — a study-plan/reminder item.
- **Tutor chat** — a grounded conversation thread scoped to a course.

---

## 5. Feature specifications

Each feature lists **what it does**, **how it works today**, and **acceptance criteria / invariants** (these encode behavior that must not regress).

### 5.1 Document processing
**What:** Ingest lecture materials (PDF/PPTX/DOCX) and extract text for downstream use.
**How:** `document_processor` agent; text extraction via PyPDF2/PyMuPDF, python-pptx, python-docx. Uploaded via `POST /api/documents/upload`; stored locally in `backend/uploads/` with metadata in Firestore.
**Acceptance criteria:**
- Supports PDF, PPTX, DOCX.
- Extracted text is available to exam/summary/flashcard/tutor generation.
- A document can be re-analyzed (`POST /api/documents/{doc_id}/reanalyze`) and deleted.

### 5.2 Audio intelligence
**What:** Turn a recording (file or YouTube URL) into structured English study notes, preserving Arabic professor quotes verbatim.
**How:** `audio_intelligence` agent — Groq Whisper (`whisper-large-v3`) for transcription, then LLM analysis. YouTube ingest via yt-dlp. Renders an analysis **PDF via XeLaTeX** (for Arabic RTL quotes).
**Acceptance criteria / invariants:**
- Summaries are in **English**, but **professor quotes stay VERBATIM in Arabic (untranslated)**.
- **Whisper prompt-echo / hallucination artifacts are stripped** before analysis.
- Audio-analysis PDF renders Arabic RTL correctly (XeLaTeX path).
- ⚠️ **Deploy blocker:** `_audio_to_latex` currently references Windows-only **"Arial"**; needs a platform check + a **bundled Arabic TTF** in the Docker image.

### 5.3 Historical (past) exam analysis
**What:** Analyze a real past exam and tag each topic as **in-scope / out-of-scope** relative to the current course's lecture documents.
**How:** `historical_exam_analyzer` agent. Upload via `POST /api/historical-exams/upload` (PDF or photo). Produces the topic/weight "intelligence" model.
**Acceptance criteria / invariants:**
- Each past-exam topic is tagged `inScope: true|false` vs. current course docs.
- The **course-scope decision lives in the analyzer** (single source of truth).
- Topic weights power both exam generation and summary likelihood %.

### 5.4 Practice exam generation ⭐ (flagship)
**What:** Generate a practice exam that mirrors the real past exam's format and marks, scoped to the current course.
**How:** `exam_generator` agent — the largest agent (~67 KB). Produces **LaTeX**, compiles to PDF with a **self-repair compile loop** (pdflatex/MiKTeX), and emits a separate **red model-answer key** PDF. Endpoints: `POST /api/exams/generate`, `POST /api/exams/generate-enhanced`.
**Acceptance criteria / invariants:**
- Generated exam mirrors the past exam's **structure, question types, and mark distribution**.
- **Scope constraint:** past-exam topics **not present in current lecture docs are EXCLUDED**, and remaining **in-scope topic weights are renormalized**.
- Two PDFs produced: the exam and a **red answer key**.
- LaTeX compile failures trigger the **self-repair loop** rather than a hard failure.
- Students can view questions, submit answers (`/api/exams/{doc_id}/submit-answers`), submit an answer document, and get a solution.

### 5.5 Summaries
**What:** Chapter-ordered summary of course material, each topic annotated with exam-likelihood %.
**How:** `POST /api/summaries/generate`; title composed from selected document names; renders a **PDF via pdflatex**.
**Acceptance criteria / invariants:**
- Topics are **chapter-ordered**; each carries an **exam-likelihood %** from real past-exam weights.
- **User exclusions honored** ("don't include topic X") via prompt **and** a post-generation filter in `api.py`.
- Summary **titles composed from selected document names**.
- **Inline markdown (`**bold**`) renders** in the summary UI, print view, and PDF.

### 5.6 Flashcards
**What:** Generate Q/A flashcards from course materials.
**How:** `POST /api/flashcards/generate`; list/detail/delete endpoints.
**Acceptance criteria:** Cards are grounded in uploaded materials; per-course listing.

### 5.7 AI tutor chat
**What:** A chat tutor that answers using *only* the student's uploaded materials, per course.
**How:** `tutor_agent`; `POST /api/tutor/chat`; threads persisted per user+course.
**Acceptance criteria / invariants:**
- Answers are **grounded in the course's materials** (no open-web facts).
- Chat threads are scoped to a `(user, course)` and persist.

### 5.8 Study schedule / reminders
**What:** Lightweight study-plan entries and reminders (weekly schedule + dashboard reminders).
**How:** `POST/PUT/GET/DELETE /api/schedule*`; `schedule_entries` collection. UI: `WeeklySchedule`, `CourseReminders`, `DashboardReminders`.

### 5.9 Cross-cutting invariants (do-not-regress)
- **Dark mode** via `[data-theme="dark"]` CSS variables; `theme.tsx` provider; light/dark both supported.
- **Global FastAPI exception handler** returns real error messages, not blank 500s.
- Bilingual UI via `i18n.tsx` / `translations.ts`.
- Per-user data isolation enforced by Firestore rules (see §7).

---

## 6. Architecture

```
┌─────────────────────────────┐        ┌──────────────────────────────────┐
│  Frontend (Next.js 14)      │  HTTP  │  Backend (FastAPI, Python)       │
│  App Router · Tailwind      │ ─────▶ │  backend/src/api.py (~2740 lines)│
│  Firebase client SDK        │        │  5 agents in src/agents/         │
│  Port 3000                  │ ◀───── │  Port 8000                       │
└─────────────────────────────┘  JSON/ └──────────────────────────────────┘
        │                        PDF          │              │
        │ auth + per-user data                │ Admin SDK    │ LLM / STT
        ▼                                     ▼              ▼
┌──────────────────┐              ┌────────────────┐   ┌──────────────────┐
│ Firebase Auth /  │              │ Firestore      │   │ OpenRouter        │
│ Firestore (client)│             │ (Admin bypass) │   │ (claude-opus-5)   │
└──────────────────┘              │ local uploads/ │   │ Groq Whisper      │
                                  │ pdflatex/XeLaTeX│  │ (whisper-large-v3)│
                                  └────────────────┘   └──────────────────┘
```

### 6.1 Frontend
- **Next.js 14 App Router**, Tailwind with a **CSS-variable theme** (light/dark).
- **Firebase client SDK** for auth + the student's own profile/course reads/writes.
- Key libs: `react-markdown` + `remark-gfm` (markdown rendering), `firebase`.
- **Routes** (`src/app/`):
  - `/` (landing), `/signin`, `/signup`, `/forgot-password`, `/settings`
  - `/dashboard`, `/dashboard/recent`, `/dashboard/bookmarked`
  - `/course/[id]` — course workspace hub
  - `/course/[id]/exam`, `/course/[id]/exam/[examId]`
  - `/course/[id]/summary`, `/course/[id]/flashcards`, `/course/[id]/tutor`
  - `/lecture/[id]`, `/lecture/[id]/processing`
- **Key components** (`src/components/`): upload modals (Document/Audio/Historical-exam/Tutorial/Lecture/Multi), `DocumentViewer`, `AudioViewer`, `WeeklySchedule`, `Sidebar`, `Navbar`, `BookmarkButton`, `CreateCourseModal`/`EditCourseModal`.
- **Key libs** (`src/lib/`): `auth-context.tsx`, `firebase.ts`, `firestore-helpers.ts`, `theme.tsx`, `i18n.tsx`, `translations.ts`, `ordering.ts`, `activity.ts`, `constants.ts`.

### 6.2 Backend
- **FastAPI**, single monolith `backend/src/api.py` (~2740 lines), entry `python -m src.api`, port 8000.
- **5 agents** (`backend/src/agents/`):
  | Agent | File | Role |
  |---|---|---|
  | Document processor | `document_processor.py` | Extract text from PDF/PPTX/DOCX |
  | Audio intelligence | `audio_intelligence.py` | Whisper transcription + hallucination cleanup + analysis |
  | Historical exam analyzer | `historical_exam_analyzer.py` | Tag past-exam topics in/out of current scope |
  | Exam generator | `exam_generator.py` | LaTeX exam + red answer key, self-repair compile loop |
  | Tutor agent | `tutor_agent.py` | Materials-grounded chat |
- **DB access:** Firebase **Admin SDK** (`src/database/firebase_client.py`) — bypasses Firestore rules.
- **PDF toolchain:** `pdflatex` (MiKTeX) for exams/summaries; **XeLaTeX** for audio-analysis PDFs (Arabic RTL).
- **File storage:** local `backend/uploads/` (served via `GET /api/files/serve`).

### 6.3 AI / model configuration (`backend/.env`)
- `OPENROUTER_MODEL=anthropic/claude-opus-5` (+ base URL, temperature, max tokens, app name/URL referer header).
- `GROQ_WHISPER_MODEL=whisper-large-v3`, `WHISPER_LANGUAGE`.
- Firebase Admin credentials path + collection name overrides; `STORAGE_BUCKET`; `LOG_LEVEL`.

---

## 7. Data model (Firestore)

Flat, per-user collections. **Every non-profile document carries a `userId` field** naming its owner.

| Collection | Purpose |
|---|---|
| `users` | Student profile (keyed by auth UID). |
| `courses` | Course containers. |
| `lectures` | Lecture/material records. |
| `exams` | Generated + historical exam records. |
| `schedule_entries` | Study-plan / reminder items. |
| `grades` | Grade/score records from submitted answers. |

**Additional logical types** surfaced by the API (documents, historical-exams, tutorials, audio recordings, flashcards, summaries, tutor chats) are managed through the endpoints in §8; keep type discrimination consistent as these are consolidated.

### 7.1 Security rules (`firestore.rules`)
- Rules govern the **frontend client SDK only**; the backend Admin SDK bypasses them.
- `users/{userId}`: read/write only if `request.auth.uid == userId`.
- All other collections: a signed-in user may only read/create/update/delete documents where `resource.data.userId == request.auth.uid`.

---

## 8. API surface (FastAPI, port 8000)

> Full list mirrors `backend/src/api.py`. Grouped by domain.

**Documents**
- `POST /api/documents/upload` · `GET /api/documents/{course_id}` · `GET /api/documents/detail/{doc_id}`
- `POST /api/documents/{doc_id}/reanalyze` · `DELETE /api/documents/{doc_id}`

**Historical exams**
- `POST /api/historical-exams/upload` · `GET /api/historical-exams/{course_id}` · `DELETE /api/historical-exams/{exam_id}`

**Tutorials**
- `POST /api/tutorials/upload` · `GET /api/tutorials/{course_id}` · `DELETE /api/tutorials/{tut_id}`

**Audio**
- `POST /api/audio/upload` · `POST /api/audio/upload-url` (YouTube) · `GET /api/audio/{course_id}`
- `GET /api/audio/{rec_id}/pdf` · `DELETE /api/audio/{rec_id}`

**Exams (generation + taking)**
- `POST /api/exams/generate` · `POST /api/exams/generate-enhanced` · `POST /api/exams/submit`
- `GET /api/exams/list/{course_id}` · `GET /api/exams/detail/{doc_id}`
- `GET /api/exams/{doc_id}/pdf` · `GET /api/exams/{doc_id}/answer-key-pdf`
- `GET /api/exams/{doc_id}/questions` · `POST /api/exams/{doc_id}/solution`
- `POST /api/exams/{doc_id}/submit-answers` · `POST /api/exams/{doc_id}/submit-document` · `DELETE /api/exams/{doc_id}`

**Summaries**
- `POST /api/summaries/generate` · `GET /api/summaries/list/{course_id}` · `GET /api/summaries/detail/{doc_id}`
- `GET /api/summaries/{doc_id}/pdf` · `DELETE /api/summaries/{doc_id}`

**Flashcards**
- `POST /api/flashcards/generate` · `GET /api/flashcards/list/{course_id}` · `GET /api/flashcards/detail/{doc_id}` · `DELETE /api/flashcards/{doc_id}`

**Intelligence**
- `GET /api/intelligence/{course_id}`

**Schedule**
- `POST /api/schedule` · `PUT /api/schedule/{entry_id}` · `GET /api/schedule/{user_id}` · `DELETE /api/schedule/{entry_id}`

**Tutor**
- `POST /api/tutor/chat` · `GET /api/tutor/chats/{user_id}/{course_id}` · `GET /api/tutor/chat/{chat_id}` · `DELETE /api/tutor/chat/{chat_id}`

**Files / health**
- `GET /api/files/serve` · `GET /`

---

## 9. Deployment plan (in progress)

**Target:** Vercel (frontend) + Dockerized backend on Render.

### 9.1 Frontend — Vercel
- [ ] Deploy Next.js app; set env for backend base URL.
- [ ] Point frontend at the deployed backend URL (not `localhost:8000`).

### 9.2 Backend — Docker on Render
The image must bundle the full toolchain:
- [ ] **LaTeX** (pdflatex) + **XeLaTeX** (e.g. TeX Live) for exam/summary/audio PDFs.
- [ ] **ffmpeg** for audio/video processing.
- [ ] **Bundled Arabic TTF font** (replaces Windows-only "Arial").
- [ ] **Platform check in `api.py` `_audio_to_latex`** — use the bundled Arabic font on Linux instead of "Arial".
- [ ] Create **`Dockerfile`** and **`render.yaml`** (not yet created).
- [ ] Persistent/writable path for `backend/uploads/` (or move to object storage — see §11).
- [ ] Backend env: `OPENROUTER_*`, `GROQ_*`, Firebase Admin credentials, `STORAGE_BUCKET`, CORS origins.

### 9.3 Firebase
- [ ] Add the deployed **frontend domain to Firebase Authorized Domains**.
- [ ] Verify Firestore rules deployed.

### 9.4 Cross-cutting
- [ ] CORS on the backend to allow the Vercel domain.
- [ ] Secrets in platform env stores (not committed) — note: `backend/.env` is currently intentionally tracked; revisit for production.

---

## 10. Cross-platform correctness checklist (Windows dev → Linux prod)

- [ ] `_audio_to_latex` Arial → bundled Arabic TTF + `platform`/OS check.
- [ ] Any hardcoded Windows paths (MiKTeX bin, ffmpeg WinGet path) replaced by PATH/env resolution.
- [ ] Local `uploads/` path assumptions valid on Render's filesystem.
- [ ] Font availability for both pdflatex and XeLaTeX in the image.

---

## 11. Risks & open questions

| # | Risk / question | Notes |
|---|---|---|
| R1 | **Local file storage doesn't survive Render restarts/scaling.** | `backend/uploads/` is ephemeral on most PaaS. Decide: persistent disk vs. Firebase Storage / S3-style object storage. `STORAGE_BUCKET` env already exists — is it wired up? |
| R2 | **Arabic font in Docker.** | Must bundle a TTF with good Arabic coverage; verify XeLaTeX shaping in-container. |
| R3 | **LLM cost / latency on Opus.** | Exam generation + self-repair loop can be token-heavy. Consider per-user rate limits / a cheaper model tier for non-flagship features. |
| R4 | **`api.py` is a ~2740-line monolith.** | Fine for now; will get harder to maintain. Candidate for modular routers as features grow. |
| R5 | **Whisper hallucination cleanup robustness.** | Verbatim-Arabic-quote invariant must survive edge cases (mixed-language, poor audio). |
| R6 | **Tracked secrets (`backend/.env`).** | Acceptable for private repo/dev; rotate + move to secret store before/at public launch. |
| R7 | **No automated tests noted.** | The generation invariants (§5) are regression-prone; consider golden-file tests for exam/summary output. |
| R8 | **Multi-user scale on single backend process.** | Long PDF/LLM jobs are synchronous; consider background jobs/queue if concurrency grows. |

---

## 12. Success criteria

**MVP is "done" when:**
1. A new student can sign up, create a course, upload docs + a past exam, and generate a practice exam PDF + red answer key that reflect the real exam's format and current-course scope.
2. Summaries generate with chapter order + exam-likelihood % and honor exclusions.
3. Flashcards and the grounded tutor work per course.
4. Audio (file + YouTube) produces an English analysis PDF with verbatim Arabic quotes — **on the deployed Linux backend**.
5. The app is **publicly reachable** (Vercel + Render), with per-user data isolation intact and Arabic PDFs rendering correctly in production.

**Quality bars (regression guards):** every invariant in §5.9 and the ⭐ items in §5.4/§5.5 hold.

---

## 13. Roadmap (suggested sequencing)

**Phase 0 — Ship public (current focus)**
- Dockerfile + render.yaml; Arabic font bundling; `_audio_to_latex` platform fix; CORS; Firebase authorized domains; storage decision (R1).

**Phase 1 — Hardening**
- Golden-file regression tests for exam/summary generation; secret rotation; basic rate limiting; error observability.

**Phase 2 — Depth**
- Richer exam config (difficulty, length, section selection); better past-exam OCR for photos; summary/flashcard exports; study-schedule notifications.

**Phase 3 — Scale (if needed)**
- Background job queue for long LLM/PDF tasks; modularize `api.py`; object storage for uploads.

---

## Appendix A — How to run (Windows dev)

Backend (needs MiKTeX + ffmpeg on PATH):
```powershell
$env:PATH="C:\Users\khali\AppData\Local\Programs\MiKTeX\miktex\bin\x64;<ffmpeg bin>;"+$env:PATH
cd backend
.\venv\Scripts\python.exe -m src.api
```
Frontend:
```powershell
npm run dev
```
> Backend code/`.env` changes require a **backend restart**; frontend hot-reloads.
