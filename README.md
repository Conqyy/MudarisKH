# Mudaris — AI Study & Exam Engine

Mudaris is an AI-driven study platform for university students (built for Imam Mohammad
Ibn Saud Islamic University). For each course it ingests the lecture documents, professor
voice recordings, past exams, and **tutorials** (practice-problem sheets), then powers a
suite of study tools: a course-grounded **AI tutor**, realistic **practice exams** (matched
to the real exam's format, each with a full **model-answer key** to self-check against),
**flashcards**, **summaries**, and a weekly **lecture calendar**.

---

## AI models (5)

Each model is independent — it never calls another model. Analyzer models write their
output to their own database table; the generation/tutor models read that stored data
back from the database. The database is the single shared source of truth.

1. **Document Processor** — extracts topics, definitions, formulas, diagrams, code, and chapter structure from lecture PDF / PPTX / DOCX (reads page images too). It has a dedicated **tutorial mode** that instead captures each practice *problem* (statement, given data/tables, what it asks, the concept, and the solving method).
2. **Audio Intelligence** — transcribes professor recordings (Groq-hosted **Whisper-large-v3**) and produces a full **lecture summary** ("what the professor said") plus exam hints, key emphasis, and chapter mapping. Accepts audio files, **video files (MP4/MOV — audio auto-extracted to MP3)**, and **video URLs** (YouTube/Vimeo/direct links, fetched with yt-dlp); long files are chunked so any length works. Transcripts are biased to the lecture's language(s) — tuned here for mixed **Arabic/English** — with stray foreign-script text filtered out, Whisper's silence hallucinations (prompt echo / subtitle credits) stripped, and bidirectional (RTL/LTR) text rendered correctly. The analysis is written in English, but the professor's **direct quotes stay verbatim in his own words** (Arabic stays Arabic), and an explicit mark statement ("this chapter is 8 marks") is treated as the strongest exam signal. The full analysis can be **downloaded as a PDF** (compiled with XeLaTeX so inline Arabic quotes render correctly).
3. **Historical Exam Analyzer** — analyzes past exams for topic weights, question-type distribution, difficulty, and grading patterns. Accepts **PDFs or photos** of the exam (each photo is analyzed as its own exam; phone photos are auto-rotated and read by the vision model).
4. **Generation agent** — produces exams (LaTeX → PDF), their **model-answer keys** (every question with the exact answer in red), flashcards, and summaries. Generated exams **mirror the selected past exam's exact question types and counts** (e.g. the same number of MCQs) and replicate its **format/layout**; the header is branded **"Mudaris University of {your major}"**. Long generations use an **auto-continuation loop** so they never truncate mid-paper.
5. **AI Tutor** — a chat tutor grounded in the course's documents, recordings, past exams, and tutorials, with its own saved chat history.

> **Tutorials** are not a 6th model — they're analyzed by the Document Processor's tutorial
> mode and then fed into the Generation agent as *problem ideas* (exam questions reuse them
> with different numbers). They never affect a generated exam's marks or format — that comes
> only from past exams.

---

## Features

- **AI Tutor** — chat about the course; answers are grounded in the lectures, recordings, past exams, and tutorials you select (each item is individually selectable). Conversations are saved and can be resumed/deleted.
- **Practice Exam** — pick which lecture documents, past exams, tutorials, and **lecture recordings** to use, choose total marks (auto-labeled **Quiz / Midterm / Final**), and generate an exam that mirrors the selected past exam's **exact question types & counts**, **format/layout**, and grading weights (the mark total only rescales the marks, never the question mix). You **solve it yourself**, then reveal a **model-answer key PDF** — every question followed by its exact answer in **red** (code answers shown as real code), so you self-check. Optionally **drag-and-drop your own solved exam** (photo, scanned PDF, or typed file) to view it side-by-side with the answers.
- **Tutorials** — upload practice-problem / exercise sheets. They're analyzed for their problem types and methods, then selectable as a source for exam generation, flashcards, and summaries (they add *problem ideas only* — never marks or format).
- **Flashcards** — up to 20 cards, prioritized by exam likelihood from past exams + professor hints, including how-to-solve cards from tutorials and points from selected **recordings**; 3-D flip study view.
- **Summary** — detailed, comprehensive study summary (a section per major topic, with full explanations, key terms, and how-to-solve notes for the tutorial problem types). Sections follow the **course's own chapter order** (Chapter 1 before Chapter 2 — not sorted by exam weight). Each topic is tagged with an exam likelihood & weight that — when past exams are available — is **derived from the past exams' topic weights** (traceable, not an LLM guess); without past exams it falls back to the model's estimate.
- **Selectable sources** — exam generation, summaries, flashcards, and the AI Tutor all let you tick exactly which documents, past exams, tutorials, and **lecture recordings** to draw from.
- **Multi-file upload** — documents, past exams, tutorials, and **recordings** can be uploaded many at once (recordings also via **multiple video URLs**, past exams also as **photos**); each item is analyzed **one at a time** with a live "done / total" counter (no batching, same quality as single uploads).
- **Weekly calendar** — Sunday–Thursday lecture schedule with start/finish times, hall notes, and no double-booking; click a lecture to edit.
- **Arabic (Najdi) + RTL** — the interface defaults to Arabic with full right-to-left layout and a one-tap **عربي ⇄ EN** toggle in the navbar (remembered per device). The copy uses a Najdi dialect and a first-person **"مُدرّس"** persona (e.g. on upload: *"مُدرّس بيقرأ مستندك ويحلّله…"*). Only the **interface** is translated — your **course content stays in its own language** (an English curriculum's topic names, exam hints, and generated material are never translated).
- **Dark mode** — a ☾/☀ toggle in the navbar flips the whole app to a warm dark theme (remembered per device, applied before first paint — no flash). The palette is CSS-variable based, so every component follows automatically.
- **Watermarked PDFs** — every generated exam and summary PDF carries a "Mudaris" mark.

---

## Architecture

| Layer | Tech |
|-------|------|
| Frontend | Next.js 14 (App Router), Tailwind CSS, Firebase client SDK |
| i18n | Lightweight `LanguageProvider` + Najdi-Arabic dictionary; Arabic/RTL default with an English toggle (interface-only) |
| Backend | Python FastAPI + Uvicorn, Firebase Admin SDK |
| AI | OpenRouter LLM (currently `anthropic/claude-opus-5`) — analysis, generation, answer keys, tutoring |
| Transcription | Groq-hosted **Whisper-large-v3** (set `GROQ_API_KEY`); long audio auto-chunked |
| Video / URL ingest | yt-dlp + ffmpeg — extract audio from MP4/MOV files and video URLs to MP3 |
| Text / file handling | PyPDF2, python-pptx, python-docx, PyMuPDF (scanned-PDF → image) |
| PDF rendering | LaTeX → PDF via pdflatex (MiKTeX); audio-analysis PDFs use XeLaTeX (bundled with MiKTeX) for Arabic/RTL quotes |
| Database | Firebase Firestore — one flat collection per data type |
| File storage | local `backend/uploads/` (cloud upload best-effort) |

---

## Prerequisites

Install these before running:

- **Python 3.11+**
- **Node.js 18+**
- **MiKTeX** — provides `pdflatex` for exam/summary PDFs · https://miktex.org/download
- **ffmpeg** — required by Whisper for audio · `winget install Gyan.FFmpeg` (Windows)
- An **OpenRouter API key** with a little credit · https://openrouter.ai
- A **Firebase** project with Firestore enabled + a service-account key

---

## How to run

> This repo is private and already includes `backend/.env` and `.env.local`. You still
> need the Firebase **service-account** key file (not committed). If you're setting up
> fresh, fill in the env values shown below.

### 1. Backend (FastAPI) — terminal 1

```bash
cd backend
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

Ensure `backend/.env` exists:

```
OPENROUTER_API_KEY=your-openrouter-key
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
OPENROUTER_MODEL=anthropic/claude-opus-5
OPENROUTER_MAX_TOKENS=8192
FIREBASE_KEY_PATH=src/config/firebase-key.json
STORAGE_BUCKET=your-bucket.firebasestorage.app
GROQ_API_KEY=your-groq-key          # transcription (Whisper-large-v3)
GROQ_WHISPER_MODEL=whisper-large-v3
WHISPER_LANGUAGE=                    # blank = auto-detect (good for mixed Arabic/English)
LOG_LEVEL=INFO
```

> `backend/.env` is **gitignored** — keep your real keys local; never commit it.

Place the Firebase service-account JSON at `backend/src/config/firebase-key.json`, then:

```bash
python -m src.api
```

Backend runs at **http://127.0.0.1:8000** (interactive API docs at `/docs`).

### 2. Frontend (Next.js) — terminal 2

```bash
npm install        # from the repo root
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

Then open **http://localhost:3000** and sign in.

---

## Typical flow

1. Sign in → create a course (it appears on the dashboard; add lectures to the weekly calendar there too).
2. On the course page, upload **documents**, **voice recordings**, **past exams**, and **tutorials** (one or many at a time) — each is analyzed by its model (status badge shows progress).
3. Use the four study tools: **AI Tutor**, **Practice Exam**, **Flashcards**, **Summary** — each lets you pick which documents / past exams / tutorials to draw from.
4. For an exam: choose total marks (Quiz/Midterm/Final) and generate (this takes **~2–3 minutes** on Opus — keep the tab open). You land on the exam page; solve it yourself, then **Reveal model answers** to get the red answer-key PDF. Optionally drop in your own solved file to compare side-by-side.

---

## Project structure

```
mudaris-dev/
├── src/                              # Next.js frontend
│   ├── app/
│   │   ├── dashboard/                # courses + weekly calendar
│   │   └── course/[id]/              # course page (documents, audio, past exams, tutorials)
│   │       ├── tutor/                # AI tutor chat
│   │       ├── exam/ + exam/[id]/    # exam generator + answer/grade
│   │       ├── flashcards/           # flashcards
│   │       └── summary/              # summary
│   ├── components/                   # viewers, modals, WeeklySchedule, etc.
│   └── lib/                          # firebase + firestore helpers
└── backend/
    └── src/
        ├── api.py                    # all FastAPI endpoints
        ├── agents/                   # 5 AI model modules
        ├── config/                   # settings + prompts
        ├── database/firebase_client.py
        └── utils/                    # compile_pdf, ai_retry
```

---

## Key API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload` · `/api/audio/upload` · `/api/historical-exams/upload` · `/api/tutorials/upload` | Upload + analyze material (audio runs in the background) |
| POST | `/api/audio/upload-url` | Transcribe a video URL (downloaded + converted to MP3 in the background) |
| GET | `/api/audio/{rec_id}/pdf` | Download a recording's analysis (summary, hints, emphasis, chapters) as a PDF |
| GET/DELETE | `/api/tutorials/{course_id}` · `/api/tutorials/{id}` | List / delete course tutorials |
| POST | `/api/exams/generate-enhanced` | Generate an exam (selected docs + past exams + tutorials, total marks) |
| GET | `/api/exams/{id}/pdf` | Recompile + serve the watermarked exam PDF |
| GET | `/api/exams/{id}/answer-key-pdf` | Build (once, cached) + serve the red model-answer key PDF |
| POST | `/api/exams/{id}/solution` | Attach the student's own solved file to view beside the answers |
| POST | `/api/flashcards/generate` · `/api/summaries/generate` | Generate flashcards / a summary |
| GET | `/api/summaries/{id}/pdf` | Watermarked summary PDF |
| POST | `/api/tutor/chat` | Chat with the AI tutor (saved to history) |
| GET/DELETE | `/api/tutor/chats/{user}/{course}` · `/api/tutor/chat/{id}` | List / load / delete tutor conversations |
| POST/GET/PUT/DELETE | `/api/schedule` ... | Weekly lecture calendar entries |
| GET | `/api/intelligence/{course_id}` | Aggregated counts of analyzed material |

---

## Notes

- AI features need OpenRouter credit. The model is one line in `backend/.env`
  (`OPENROUTER_MODEL`) — and the matching value in `render.yaml` for the deployed
  backend. It currently uses `anthropic/claude-opus-5` for best quality
  ($5 / $25 per M input / output tokens). To cut costs, `anthropic/claude-sonnet-5`
  is ~2.5× cheaper and `anthropic/claude-haiku-4.5` ~5× cheaper. Opus is a reasoning
  model, so exam generation can take ~2–3 minutes and costs more per call.
- The **model-answer key** is built from the exam's own answer rubric (no extra AI call in
  the common case) and compiled locally, so revealing answers is usually fast and free.
- Generated PDFs require MiKTeX; audio transcription requires ffmpeg.
- Keep this repository **private** — `backend/.env` (API key) is tracked here by choice.
  Rotate the key if the repo's access ever changes.
