# Mudaris — AI Study & Exam Engine

Mudaris is an AI-driven study platform for university students (built for Imam Mohammad
Ibn Saud Islamic University). For each course it ingests the lecture documents, professor
voice recordings, past exams, and **tutorials** (practice-problem sheets), then powers a
suite of study tools: a course-grounded **AI tutor**, realistic **practice exams** (matched
to the real exam's format, each with a full **model-answer key** to self-check against),
**flashcards**, **summaries**, and a weekly **lecture calendar**.

---

## Agent architecture

The backend has five Python agent modules, coordinated by FastAPI. They are components
inside the same backend process, not five separate network services or necessarily five
different LLMs. Analysis, generation, and tutoring use the configured OpenRouter model;
transcription uses Groq separately.

Agents return their results to the API. The API and audio worker persist those results
through `FirebaseClient`; generation and tutor requests load the selected stored material
and pass it as context. Agents do not send messages directly to one another. Firestore is
the shared source of truth for analyses and conversation history.

1. **Document Processor** — extracts topics, definitions, formulas, diagrams, code, and chapter structure from lecture PDF / PPTX / DOCX (reads page images too). It has a dedicated **tutorial mode** that instead captures each practice *problem* (statement, given data/tables, what it asks, the concept, and the solving method).
2. **Audio Intelligence** — transcribes professor recordings (Groq-hosted **Whisper-large-v3**) and produces a full **lecture summary** ("what the professor said") plus exam hints, key emphasis, and chapter mapping. Accepts audio files, **video files (MP4/MOV — audio auto-extracted to MP3)**, and **video URLs** (YouTube/Vimeo via yt-dlp; direct media through a validated downloader); long files are chunked within the upload, duration, and processing limits. Transcripts are biased to the lecture's language(s) — tuned here for mixed **Arabic/English** — with stray foreign-script text filtered out, Whisper's silence hallucinations (prompt echo / subtitle credits) stripped, and bidirectional (RTL/LTR) text rendered correctly. The analysis is written in English, but the professor's **direct quotes stay verbatim in his own words** (Arabic stays Arabic), and an explicit mark statement ("this chapter is 8 marks") is treated as the strongest exam signal. The full analysis can be **downloaded as a PDF** (compiled with XeLaTeX so inline Arabic quotes render correctly).
3. **Historical Exam Analyzer** — analyzes past exams for topic weights, question-type distribution, difficulty, and grading patterns. Accepts **PDFs or photos** of the exam (each photo is analyzed as its own exam; phone photos are auto-rotated and read by the vision model).
4. **Generation agent** — produces exams (LaTeX → PDF), their **model-answer keys** (every question with the exact answer in red), flashcards, and summaries. The **first selected past exam** defines the required question types and counts (e.g. the same number of MCQs). Prompts use its format/layout as a reference; validators check question structure and printed marks, rather than pixel-identical layout. The requested mark total rescales the rubric and printed marks together; the header is branded **"Mudaris University of {your major}"**. Long generations use a bounded **auto-continuation loop**; incomplete output is rejected instead of saved as successful.
5. **AI Tutor** — a chat tutor grounded in the course's documents, recordings, past exams, and tutorials, with its own saved chat history.

> **Tutorials** are not a 6th model — they're analyzed by the Document Processor's tutorial
> mode and supplied as practice-problem context. They do not define an exam's question mix
> or total marks. When selected, historical exams define the question mix; the student's
> requested mark total defines the total.

---

## Features

- **AI Tutor** — chat about the course; answers are grounded in the lectures, recordings, past exams, and tutorials you select (each item is individually selectable). Conversations are saved and can be resumed/deleted.
- **Practice Exam** — pick which lecture documents, past exams, tutorials, and **lecture recordings** to use, choose total marks (auto-labeled **Quiz / Midterm / Final**), and generate an exam whose question types and counts match the **first selected past exam**, with its layout used as a prompt reference (the mark total only rescales the marks, never the question mix). You **solve it yourself**, then reveal a **model-answer key PDF** — every question followed by its exact answer in **red** (code answers shown as real code), so you self-check. Optionally **drag-and-drop your own solved exam** (photo, scanned PDF, or typed file) to view it side-by-side with the answers.
- **Tutorials** — upload practice-problem / exercise sheets. They're analyzed for their problem types and methods, then selectable as a source for exam generation, flashcards, and summaries (they add *problem ideas only* — never marks or format).
- **Flashcards** — up to 20 cards, prioritized by exam likelihood from past exams + professor hints, including how-to-solve cards from tutorials and points from selected **recordings**; 3-D flip study view.
- **Summary** — detailed, comprehensive study summary (a section per major topic, with full explanations, key terms, and how-to-solve notes for the tutorial problem types). Sections follow the **course's own chapter order** (Chapter 1 before Chapter 2 — not sorted by exam weight). Each topic is tagged with an exam likelihood & weight that — when past exams are available — is **derived from the past exams' topic weights** (traceable, not an LLM guess); without past exams it falls back to the model's estimate.
- **Selectable sources** — exam generation, summaries, flashcards, and the AI Tutor use the documents, past exams, tutorials, and **lecture recordings** you select. At the API, omitted/null ID lists include all of that type; `[]` excludes all. Explicit source order is preserved and duplicate IDs are removed. Generation rejects an empty effective selection. Later selected past papers add content and weighting signals; the first defines the exam structure.
- **Multi-file upload** — documents, past exams, tutorials, and **recordings** can be uploaded many at once (recordings also via **multiple video URLs**, past exams also as **photos**); each item is analyzed **one at a time** with a live "done / total" counter (sequential processing).
- **Weekly calendar** — Sunday–Thursday lecture schedule with start/finish times, hall notes, and no double-booking; click a lecture to edit.
- **Arabic (Najdi) + RTL** — the interface supports right-to-left layout and a one-tap **عربي ⇄ EN** toggle in the navbar (remembered per device). The copy uses a Najdi dialect and a first-person **"مُدرّس"** persona (e.g. on upload: *"مُدرّس بيقرأ مستندك ويحلّله…"*). Interface translations are available; some study-workflow labels still use English fallback. Your **course content stays in its own language** (an English curriculum's topic names, exam hints, and generated material are never translated).
- **Dark mode** — a ☾/☀ toggle in the navbar flips the whole app to a warm dark theme (remembered per device, applied before first paint — no flash). The palette is CSS-variable based, so every component follows automatically.
- **Watermarked PDFs** — generated exams, summaries, and audio-analysis PDFs carry a "Mudaris" mark.
- **Retries and isolated chats** — failed document/audio analyses can reuse saved material; previews and answer-key PDFs have explicit retry controls. Late tutor replies cannot enter a different conversation, and concurrent replies cannot overwrite the same saved history.
- **Cascading deletion** — course/account deletion uses authenticated backend cleanup for owned materials, chats, schedules, rubrics, solutions, and local/cloud uploads. Account cleanup requires recent authentication and completes before deleting the Auth account. Failed cleanup can be retried.

---

## Architecture

| Layer | Tech |
|-------|------|
| Frontend | Next.js 15 (App Router), React 19, Tailwind CSS, Firebase client SDK |
| i18n | `LanguageProvider` + Najdi-Arabic dictionary; English/LTR default, saved Arabic/RTL toggle, English fallback for missing translations |
| Backend | Python FastAPI + Uvicorn, Firebase Admin SDK |
| AI | OpenRouter model selected by `OPENROUTER_MODEL`; repository default is `google/gemini-3.1-pro-preview` |
| Transcription | Groq-hosted **Whisper-large-v3** (set `GROQ_API_KEY`); long audio auto-chunked |
| Video / URL ingest | yt-dlp for supported platforms, validated direct downloads, restricted ffmpeg media conversion |
| Text / file handling | pypdf, python-pptx, python-docx, PyMuPDF (scanned-PDF → image) |
| PDF rendering | pdflatex for exams/answer keys; XeLaTeX for Unicode summary/audio PDFs, with Arabic font fallbacks |
| Database | Firebase Firestore flat collections; transactions protect writes, conversations, schedules and deletion guards |
| File storage | Anchored `backend/uploads/` plus optional private Firebase Storage copy; authenticated API serving |

---

## Prerequisites

Install these before running:

- **Python 3.12** (verified with the dependency lock)
- **Node.js 20.19+, 22.12+, or 24+**, matching `package.json`; verified with Node 24.15
- **MiKTeX** — provides `pdflatex` for exam PDFs and `xelatex` for Unicode summary/audio PDFs · https://miktex.org/download
- **ffmpeg** — local audio conversion and transcription chunking · `winget install Gyan.FFmpeg` (Windows)
- An **OpenRouter API key** with a little credit · https://openrouter.ai
- A **Firebase** project with Authentication and Firestore enabled, a service-account key, and a Storage bucket for optional cloud copies
- A **Groq API key** for recording transcription; typed notes do not need transcription

---

## How to run

> A fresh clone gives you `.env.local` (tracked), but **not** `backend/.env` or the
> Firebase **service-account** key — both are gitignored. Create them from the values
> shown below; `backend/.env.example` is the template for the first.

### 1. Backend (FastAPI) — terminal 1

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.lock.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

On macOS/Linux, use `source .venv/bin/activate` and `cp .env.example .env`.
The lock includes the application and regression-test dependencies. Edit an existing
`.env` in place. On macOS/Linux, copy the template only if `.env` does not already exist.

Ensure `backend/.env` exists:

```
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=google/gemini-3.1-pro-preview
OPENROUTER_MAX_TOKENS=8192
FIREBASE_KEY_PATH=src/config/firebase-key.json
STORAGE_BUCKET=your-bucket.firebasestorage.app
GROQ_API_KEY=your-groq-key          # transcription (Whisper-large-v3)
GROQ_WHISPER_MODEL=whisper-large-v3
WHISPER_LANGUAGE=                    # blank = auto-detect (good for mixed Arabic/English)
MUDARIS_RELOAD=0
```

> `backend/.env` is **gitignored** — keep your real keys local; never commit it.

Place the Firebase service-account JSON at `backend/src/config/firebase-key.json`, then:

```bash
python -m src.api
```

Backend runs at **http://127.0.0.1:8000** (interactive API docs at `/docs`).

### 2. Frontend (Next.js) — terminal 2

```bash
npm ci             # from the repo root; use the committed lockfile
npm run dev
```

Frontend runs at **http://localhost:3000**.

Ensure `.env.local` (repo root) has your Firebase web config + backend URL:

```
NEXT_PUBLIC_FIREBASE_API_KEY=...
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=...
NEXT_PUBLIC_FIREBASE_PROJECT_ID=...
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=...
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=...
NEXT_PUBLIC_FIREBASE_APP_ID=...
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
```

Use the web configuration for the same Firebase project as the backend service account.
Enable the desired sign-in providers and authorize `localhost` in Firebase Authentication.
Publish the checked-in Firestore rules to that project:

```powershell
# From the repository root, with an authenticated Firebase CLI
firebase deploy --only firestore:rules --project YOUR_PROJECT_ID
```

`firebase.json` points to `firestore.rules`. Select the project deliberately; Git pushes
do not deploy Firebase rules. Then open **http://localhost:3000** and sign in.

---

## Typical flow

1. Sign in → create a course (it appears on the dashboard; add lectures to the weekly calendar there too).
2. On the course page, upload **documents**, **voice recordings**, **past exams**, and **tutorials** (one or many at a time) — each is analyzed by its model (status badge shows progress).
3. Use the four study tools: **AI Tutor**, **Practice Exam**, **Flashcards**, **Summary** — each lets you pick which documents / recordings / past exams / tutorials to draw from.
4. For an exam: choose total marks (Quiz/Midterm/Final) and generate. Completion time depends on the provider and selected material. You land on the exam page; solve it yourself, then **Reveal model answers** to get the red answer-key PDF. Optionally drop in your own solved file to compare side-by-side.

---

## Project structure

```
MudarisKH/
├── src/                              # Next.js frontend
│   ├── app/
│   │   ├── dashboard/                # courses + weekly calendar
│   │   └── course/[id]/              # course page (documents, audio, past exams, tutorials)
│   │       ├── tutor/                # AI tutor chat
│   │       ├── exam/ + exam/[examId]/ # exam generator, model answers and own solution
│   │       ├── flashcards/           # flashcards
│   │       └── summary/              # summary
│   ├── components/                   # viewers, modals, WeeklySchedule, etc.
│   └── lib/                          # auth, API, storage, lifecycle and UI helpers
├── tests/frontend/                   # Vitest + React regression tests
├── firebase.json                     # explicit Firestore rules configuration
├── firestore.rules                   # client permissions and deletion guards
└── backend/
    ├── requirements.lock.txt         # verified Python application/test dependencies
    ├── tests/                        # API, lifecycle, AI, media and PDF regressions
    └── src/
        ├── api.py                    # all FastAPI endpoints
        ├── agents/                   # five agent modules
        ├── config/                   # settings + prompts
        ├── database/firebase_client.py
        └── utils/                    # validated storage, AI contracts, jobs, media and PDF helpers
```

---

## Key API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload` · `/api/audio/upload` · `/api/historical-exams/upload` · `/api/tutorials/upload` | Upload + analyze material; audio defaults to background processing, while the multi-upload UI waits sequentially |
| POST | `/api/audio/upload-url` · `/api/audio/upload-notes` | Ingest a supported media URL or analyze typed lecture notes |
| POST | `/api/documents/{doc_id}/reanalyze` · `/api/audio/{rec_id}/reanalyze` | Retry saved document/audio analysis |
| GET | `/api/files/serve?path=...` | Serve an owned upload through Firebase token authentication |
| GET | `/api/audio/{rec_id}/pdf` | Download a recording's analysis (summary, hints, emphasis, chapters) as a PDF |
| GET/DELETE | `/api/tutorials/{course_id}` · `/api/tutorials/{id}` | List / delete course tutorials |
| POST | `/api/exams/generate-enhanced` | Generate an exam (selected docs + recordings + past exams + tutorials, total marks) |
| GET | `/api/exams/{id}/pdf` | Recompile + serve the watermarked exam PDF |
| GET | `/api/exams/{id}/answer-key-pdf` | Build (once, cached) + serve the red model-answer key PDF |
| POST | `/api/exams/{id}/solution` | Attach the student's own solved file to view beside the answers |
| POST | `/api/flashcards/generate` · `/api/summaries/generate` | Generate flashcards / a summary |
| GET | `/api/summaries/{id}/pdf` | Watermarked summary PDF |
| POST | `/api/tutor/chat` | Chat with the AI tutor (saved to history) |
| GET | `/api/tutor/chats/{user_id}/{course_id}` · `/api/tutor/chat/{chat_id}` | List / load owned tutor conversations |
| DELETE | `/api/tutor/chat/{chat_id}` | Delete an owned conversation |
| POST | `/api/schedule` | Create a weekly lecture entry |
| GET | `/api/schedule/{user_id}` | List the authenticated user's schedule |
| PUT/DELETE | `/api/schedule/{entry_id}` | Update / delete an owned schedule entry |
| DELETE | `/api/courses/{course_id}` | Cascade cleanup for an owned course |
| DELETE | `/api/account` | Purge application data, then Auth; recent sign-in required |
| GET | `/api/intelligence/{course_id}` | Aggregated counts of analyzed material |

Data endpoints require `Authorization: Bearer <Firebase ID token>` and derive ownership
from the verified token, rather than trusting a supplied user ID. Account deletion requires
a sign-in within five minutes. If cleanup returns 503, retry while still signed in.
Exam PDF and answer-key paths use the saved document ID (`doc_id`), not the generated
exam identifier (`exam_id`). The root health route and API documentation are public;
a health response alone does not verify Firebase, AI providers, or the PDF compiler.

---

## Notes

- The checked-in setup runs Next.js locally and binds FastAPI to `127.0.0.1:8000`,
  with localhost CORS. Firebase and AI providers remain external services. A GitHub push
  publishes source; it does not establish a hosted application or apply cloud migrations.
- AI features require configured OpenRouter/Groq credentials and available credit. Select the
  model with `OPENROUTER_MODEL` in `backend/.env`; provider availability, pricing and latency
  are external configuration, not guarantees made by this repository.
- An uncached **model-answer key** can call the LLM for worked solutions, then a structured
  answer fallback. Only complete output is accepted. Cached keys avoid repeating generation;
  a deterministic rubric key is a final fallback when it is complete and compiles.
- Generated PDFs require MiKTeX; audio transcription requires ffmpeg.
- **Secrets are not in git.** `backend/.env` (OpenRouter + Groq keys) and the Firebase
  service-account key are gitignored — copy
  `backend/.env.example` and fill in your own. The one env file that *is* tracked,
  `.env.local`, holds only `NEXT_PUBLIC_*` values — the Firebase web config and the
  backend URL — which are public client identifiers rather than secrets; per-user access
  is enforced by deployed `firestore.rules` and the ID-token check on data endpoints.

## Verification

Run checks from the repository root after installing both dependency environments:

```powershell
# Repository root
npm ci
npm test
npm run lint
npx tsc --noEmit --incremental false
npm run build

# Repository root, after creating backend/.venv
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
```

For a separate build output set `NEXT_BUILD_DIR=.next-verify` in your shell before
building and starting Next. The local launcher uses `backend/.venv`.
Start the backend from `backend/` to load its
environment and credential path. Uploads and local JSON are anchored to that directory.

New uploads are private and served through the authenticated file endpoint. The revised
`firestore.rules` must be published to the intended Firebase project before client-side
write restrictions apply there. Existing public blobs require a separate ACL cleanup.

Last verified on **9 October 2026**: 156 backend tests plus six subtests, 78 frontend
tests, TypeScript, lint, and the production build passed. Lint retains one App Router
font warning. Browser smoke checks covered home/sign-in navigation and Arabic RTL.
Tests use fake Firebase/model clients; they do not delete live accounts or spend credits.

## Processing and deployment limits

- Documents, historical exams, tutorials and solution uploads are capped at 100 MiB;
  audio/video uploads and direct media downloads at 512 MiB. Supported platform URL
  metadata is checked for a four-hour duration limit. Saved records use a conservative
  750,000-byte JSON-size check; oversized content is rejected rather than silently cut.
- Text context and PDF vision pages are bounded. Balanced excerpts and source provenance
  are stored with generated material; this does not guarantee every source detail appears
  in a model response. Schema checks detect incomplete output, not factual correctness.
- Audio uses a bounded in-process worker pool and persisted statuses for restart recovery.
  Multiple backend processes need distributed job claims. Canceling a browser request
  prevents stale UI updates but does not guarantee cancellation of provider work.
- Public hosting needs explicit backend bind/CORS configuration for the intended HTTPS
  frontend and durable storage. Cloud upload is best-effort; a missing local file can be
  restored only if its private cloud copy exists. Local JSON fallback does not supply
  offline authentication or AI providers.
- New uploads are private. Existing public object ACLs/download tokens require separate
  review. Apply the revised Firestore rules before relying on their client restrictions.
  Small deletion tombstones remain after cleanup to block late recreation.
- TeX has source checks, disabled shell escape, time limits, and temporary-file cleanup;
  it is not an OS sandbox. Finish MiKTeX setup and validate real PDF output on the target
  machine. Arabic fonts fall back through Arial, Amiri, Noto Naskh Arabic, and DejaVu Sans.
- The last dependency check found no known production npm or installed backend findings.
  Seven development-tool findings remain from an
  [unpatched braces advisory](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm).
  Re-run dependency audits as advisories and dependencies change.
