# Mudaris — AI Study & Exam Engine

Mudaris is an AI-driven study platform for university students (built for Imam Mohammad
Ibn Saud Islamic University). For each course it ingests the lecture documents, professor
voice recordings, past exams, and **tutorials** (practice-problem sheets), then powers a
suite of study tools: a course-grounded **AI tutor**, predicted **practice exams** (informed
by all selected past papers, each with a full **model-answer key** to self-check against),
**flashcards**, **summaries**, and a weekly **lecture calendar**.

---

## Agent architecture

The backend has six Python agent modules, coordinated by FastAPI. They are components
inside the same backend process, not six separate network services or necessarily six
different LLMs. Analysis, generation, and tutoring use the configured OpenRouter model;
transcription uses Groq separately.

Agents return their results to the API. The API and document/audio workers persist
results through `FirebaseClient`. A request-local source reader supplies selected original
lecture passages and images, the automatic guide, and source references to downstream
agents. Agents do not send messages directly to one another. Firestore holds compact
records and conversation history; original files and complete source manifests are private
storage artifacts.

Lecture documents are the mandatory foundation. Each upload preserves its original,
prepares location-aware source material, and automatically creates a lightweight academic
guide. There is no switch to skip either stage. Upload all intended documents, wait for
every document to finish **Preparing document** and **Creating lightweight analysis**, then
select **I've uploaded all lecture documents**.
Past exams, tutorials, recordings, and study tools display locks until that confirmation.
The API enforces the same prerequisite, including direct requests and recovered audio jobs.
Adding, deleting, replacing, or retrying documents invalidates confirmation and requires
it again after both stages succeed. Failed preparation and failed guide creation have
separate retry controls; a completed preparation can be reused for a guide retry. Legacy
lecture uploads require explicit preparation from their saved originals rather than
unlocking from old sampled analysis. Existing saved outputs and cleanup remain available.
Confirmation is stored in backend-only `document_foundations` records, separate from course
presentation metadata, and is included in course/account cleanup.

Audio, historical-paper and tutorial analysis receive actual original lecture evidence and
the guide in bounded requests. Generation requires at least one selected prepared lecture
document to define its academic scope; the tutor receives foundation documents when no
lecture resources are selected. Guides help navigation and never act as topic whitelists.
Original material stays in user-message evidence, separate from trusted system policy.
New results carry source-version references and execution coverage. Publication checks the
confirmed foundation and current owned document identities/stages atomically, so changed
or retried material cannot authorize a late save.

1. **Document Processor** — supports complete location-aware preparation of lecture PDF / PPTX / DOCX, extraction-only visual reading, and an automatic guide of sections, concepts, visual references, and warnings. PDF pages, PPTX slides/text/tables/notes/images, and DOCX paragraph/table/image locations remain addressable. The guide does not regenerate a full set of definitions or formulas; agents read those from the originals. Its dedicated **tutorial mode** captures each practice *problem* (statement, given data/tables, what it asks, the concept, and the solving method), with lecture evidence for alignment.
2. **Audio Intelligence** — transcribes professor recordings (Groq-hosted **Whisper-large-v3**) and produces a full **lecture summary** ("what the professor said") plus exam hints, key emphasis, and chapter mapping. Accepts audio files, **video files (MP4/MOV — audio auto-extracted to MP3)**, and **video URLs** (YouTube/Vimeo via yt-dlp; direct media through a validated downloader); long files are chunked within the upload, duration, and processing limits. Transcripts are biased to the lecture's language(s) — tuned here for mixed **Arabic/English** — with stray foreign-script text filtered out, Whisper's silence hallucinations (prompt echo / subtitle credits) stripped, and bidirectional (RTL/LTR) text rendered correctly. The analysis is written in English, but the professor's **direct quotes stay verbatim in his own words** (Arabic stays Arabic), and an explicit mark statement ("this chapter is 8 marks") is treated as the strongest exam signal. The full analysis can be **downloaded as a PDF** (compiled with XeLaTeX so inline Arabic quotes render correctly).
3. **Historical Exam Analyzer** — detects individual papers inside merged PDFs, inspects every page in sequential batches, and analyzes each paper for topic weights, question types, difficulty, and grading patterns. It stores per-paper evidence plus normalized aggregate statistics; the typical question count is separate from the collection total. Phone photos are auto-rotated and analyzed individually. Unclear paper boundaries fail with guidance to split the file, rather than silently treating a collection as one paper.
4. **Exam Generator** — produces a **predicted single exam** from all selected past papers, its **model-answer key**, and flashcards. Each paper contributes normalized evidence equally. Structure favors the requested Quiz/Midterm/Final type where known; typical question density or count and the requested marks determine the new blueprint. Upload order does not choose a reference paper. The blueprint and provenance are saved with the exam, and validators check its question mix, complete rubrics, and printed marks. The header is branded **"Mudaris University of {your major}"**. Long generations use a bounded continuation loop; incomplete output is rejected.
5. **Summary Generator** — independently produces structured summaries with length determined by relevant content, complexity, importance, and student instructions, without fixed section/paragraph/term targets. It excludes course outlines/maps, textbook lists, and logistics by default while retaining substantive introductory concepts. Shared context-formatting helpers are neutral; its prompt, model call, and validation are separate from exams.
6. **AI Tutor** — a chat tutor that reads relevant selected original lecture evidence alongside supporting materials and saved history. Academic replies require validated source references and factual checks; social/clarification replies may be reference-free after a separate nonacademic check.

> **Tutorials** are not another model — they're analyzed by the Document Processor's tutorial
> mode and supplied as practice-problem context. They do not define an exam's question mix
> or total marks. When selected, historical exams define the question mix; the student's
> requested mark total defines the total.

---

## Features

- **AI Tutor** — chat about the course using individually selected lectures, recordings, past exams, and tutorials. Original lectures ground academic replies; exact-version citations open source previews. Conversations and their per-reply provenance are saved and can be resumed/deleted.
- **Practice Exam** — select lecture documents, past papers, tutorials, and **lecture recordings**, choose total marks (auto-labeled **Quiz / Midterm / Final**), and generate a predicted paper based on recurring patterns across all selected papers. Merged PDFs are separated into individual papers; selected older uploads are rescanned from saved originals and cached before generation. Question counts are never summed across a collection. You **solve it yourself**, then reveal a **model-answer key PDF** with answers in **red**, including real code where required. Optionally upload your own solved paper for side-by-side comparison.
- **Tutorials** — upload practice-problem / exercise sheets. They're analyzed for their problem types and methods, then selectable as a source for exam generation, flashcards, and summaries (they add *problem ideas only* — never marks or format).
- **Flashcards** — up to 20 cards, prioritized by exam likelihood from past exams + professor hints, including how-to-solve cards from tutorials and points from selected **recordings**; 3-D flip study view.
- **Summary** — content-sized study notes with important explanations, key terms, and tutorial-solving methods. Related ideas can share a section; no numeric size quota encourages padding. Course administration is omitted by default. Sections follow the **course's chapter order**. Exam weights are relative study signals derived from matching historical topic weights where available; otherwise model estimates remain. They are not calibrated probabilities of future exam coverage.
- **Selectable sources** — exam generation, summaries, flashcards, and the AI Tutor use selected documents, past exams, tutorials, and **lecture recordings**. At the API, omitted/null ID lists include all of that type; `[]` excludes all. Exam/summary/flashcard generation requires a nonempty lecture selection. For tutoring, a confirmed document foundation remains required and is included when no documents are selected. Explicit source order is preserved and duplicate IDs are removed. Exam prediction combines all detected papers without giving the first upload special authority.
- **Multi-file upload** — documents, past exams, tutorials, and **recordings** can be uploaded many at once (recordings also via **multiple video URLs**, past exams also as **photos**). The interface processes files sequentially with a live "done / total" counter. Document acceptance starts polling; a file counts as done only after preparation and guide creation both succeed. Failed files retain their reasons and the batch can continue.
- **Original sources and citations** — the document viewer shows guide sections/concepts, source-unit metadata, and preparation warnings. Authenticated original PDF viewing remains available while locked. Prepared PPTX/DOCX files use source units; legacy Office files show preparation guidance instead of an empty Content view. Summary sections, flashcards, exam-question metadata, and tutor replies link to exact source versions; unavailable versions show guidance and never open replacement content at the same page/slide position. Machine references stay off the printed exam sheet.
- **Weekly calendar** — Sunday–Thursday lecture schedule with start/finish times, hall notes, and no double-booking; click a lecture to edit.
- **Arabic (Najdi) + RTL** — the interface supports right-to-left layout and a one-tap **عربي ⇄ EN** toggle in the navbar (remembered per device). The copy uses a Najdi dialect and a first-person **"مُدرّس"** persona (e.g. on upload: *"مُدرّس بيقرأ مستندك ويحلّله…"*). Interface translations are available; some study-workflow labels still use English fallback. Your **course content stays in its own language** (an English curriculum's topic names, exam hints, and generated material are never translated).
- **Dark mode** — a ☾/☀ toggle in the navbar flips the whole app to a warm dark theme (remembered per device, applied before first paint — no flash). The palette is CSS-variable based, so every component follows automatically.
- **Watermarked PDFs** — generated exams, summaries, and audio-analysis PDFs carry a "Mudaris" mark.
- **Retries and isolated chats** — document jobs have durable stage checkpoints, leases and startup recovery; incomplete preparation can retry from the saved original, while a failed guide can reuse completed preparation. Failed/legacy documents are retried explicitly. Audio analysis, previews and answer-key PDFs retain retry controls. Late uploads/previews/replies are fenced on account/course/selection changes, and concurrent tutor replies cannot overwrite the same saved history.
- **Cascading deletion** — course/account deletion uses authenticated backend cleanup for owned materials, chats, schedules, rubrics, solutions, and local/cloud uploads. Account cleanup requires recent authentication and completes before deleting the Auth account. Failed cleanup can be retried.

---

## How source evidence is used

Selected lecture identities and source locations form the hard academic scope. Invalid,
foreign or unavailable explicit selections fail rather than silently switching to all
documents. Original passages and images determine facts; the automatic guide helps agents
navigate. Guide omissions, matching vocabulary, or a failed lookup do not prove that a
topic is absent. Supporting topics need actual selected-source support before influencing
academic content, while historical counts/types/marks remain independent structural
evidence for the predicted exam.

Tutor requests validate explicit nonempty document selections before filtering resources;
missing, foreign or unavailable IDs reject the request, including mixed valid/invalid
selections. Only omitted/null or intentionally empty tutor document selections use the
confirmed foundation. Async historical/tutorial uploads run blocking lecture readiness,
source preparation and topic alignment in worker threads alongside their provider calls.

Exam, summary and flashcard requests read all selected source units in bounded batches.
Coverage records successful text ranges and original image submissions, including partial
units and structural blanks; a plan alone is not completed coverage. Draft synthesis uses
all extracted task facts plus explicitly partial original windows. Factual verification
rereads cited originals and checks supported output spans. Exams independently check
shared academic instructions/data and preamble macros, then check each question and its
authoritative rubric with that shared context and the cited originals, including images.
Generated shared text is interpretive context, not original evidence. Focused tutor/supporting
lookups remain partial. Excessive source/context budgets fail with select/split guidance.

New citations use `{documentId, sourceRevision, unitId}` and are checked against ownership,
selection, exact versions and the server's successful-submission ledger. These checks
establish provenance and enforce model judgments of factual support; they do not prove
perfect OCR, complete understanding, or accurate future-exam predictions.

Saved exam detail is a read and never starts model rescue. Available saved TeX can compile
while the course is locked. Answer keys first try a valid cache, then complete saved
rubrics; those paths do not require current confirmation or available lecture originals.
Modern caches bind exact saved inputs, output TeX and ordered question/reference mappings.
Legacy outputs retain compatible detail and count-based cache reads.

New AI repair or answer explanations restore the exam's exact old original versions and
saved validated guide, not today's lecture selection. Missing or inconsistent saved
scope/identity returns restore/regenerate guidance before a provider call. A separate
current confirmed foundation authorizes publication without replacing original provenance.
Repair preserves exact questions, official answers/rubrics, printed marks and shared
academic context; only narrow harmless layout changes may be saved. New explanations
must map to the exact saved question and official answer. Atomic writes also check that
the saved exam itself has not changed or been deleted.

Public exam detail omits secret rubrics, answer caches, private saved guides and original
storage maps/paths. Its solution preview may retain a validated relative generated-output
locator, `solutions/<same owner>/<same course>/<filename>`; the authenticated file route
enforces access. It is not a lecture-original pointer. Exact owned unavailable source
previews return 409 guidance; foreign/missing documents remain 404, and omitting the
required `source_revision` returns 422.

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
| PDF rendering | pdflatex for exams/retained answer keys; XeLaTeX for new structured answer fallbacks and Unicode summary/audio PDFs, with Arabic font fallbacks |
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
2. Upload all intended **lecture documents**. Follow the upload, preparation and lightweight-analysis stages; retry a failed stage or explicitly prepare a legacy upload. Missing originals or unresolved source coverage must be restored/replaced before confirmation.
3. When every document finishes both stages, select **I've uploaded all lecture documents**. Adding, removing, replacing or retrying lecture documents locks new supporting/AI work until the completed set is confirmed again.
4. Upload **voice recordings**, **past exams**, and **tutorials**. Then use **AI Tutor**, **Practice Exam**, **Flashcards**, or **Summary**, choosing the source items for each request. Selected lecture documents define academic scope; supporting material cannot reintroduce an unselected chapter.
5. For an exam, choose total marks (Quiz/Midterm/Final) and generate one predicted paper informed by all selected past papers. Solve it yourself, then **Reveal model answers** to open the red answer-key PDF. Optionally attach your own solved file for comparison. Completion time depends on the provider, source size and required source readings.

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
        ├── agents/                   # six agent modules
        ├── config/                   # settings + prompts
        ├── database/firebase_client.py
        ├── services/                 # private source library, preparation pipeline, request-local evidence reader
        └── utils/                    # validated storage, AI contracts, jobs, media and PDF helpers
```

---

## Key API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/documents/upload` · `/api/audio/upload` · `/api/historical-exams/upload` · `/api/tutorials/upload` | Upload material; documents return 202 and run mandatory preparation + guide jobs; audio defaults to background processing; the UI waits per file |
| POST | `/api/audio/upload-url` · `/api/audio/upload-notes` | Ingest a supported media URL or analyze typed lecture notes |
| POST | `/api/documents/{doc_id}/prepare` · `/api/documents/{doc_id}/reanalyze` | Prepare/upgrade a saved lecture source or retry its guide; returns accepted identity for status polling |
| GET | `/api/documents/detail/{doc_id}` · `/api/documents/{doc_id}/sources` | Poll document stages or inspect compact source-unit/coverage metadata |
| GET | `/api/documents/{doc_id}/original` | View the owned current original while locked; independent of citation-version resolution |
| GET | `/api/documents/{doc_id}/sources/{unit_id}?source_revision=...` | Preview an owned exact source version/location; never fall back to a replacement source |
| POST | `/api/audio/{rec_id}/reanalyze` | Retry saved recording analysis |
| GET/POST | `/api/courses/{course_id}/foundation` · `/api/courses/{course_id}/foundation/confirm` | Read readiness or confirm the displayed completed lecture-set revision |
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
- **Model-answer keys** first try a valid cache, then complete deterministic saved-rubric
  compilation. New AI explanations require restorable saved originals/guide and current
  confirmation; exact question IDs/bodies, official answers and source references must
  validate. Count-only model output cannot authorize a new key.
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

Source-first implementation reports cover backend extraction/library/jobs/scope/agent
integration and frontend stages/citations/lifecycle regressions. Tests use deterministic
provider stubs and local or simulated cloud boundaries; they do not delete live accounts
or spend credits. They establish wiring and guarded behavior, not live provider/cloud
performance. After the 15 October review fixes, 856 backend tests plus 6 subtests passed,
with one existing Cloud durability boundary skip; 166 frontend tests, TypeScript and the
production build passed. Lint retains the existing layout-font warning. Installed-compiler
checks and visual inspection passed for English, Arabic and mixed structured answer
fallbacks, including code indentation; this does not establish every possible PDF input.
The four whole-branch findings are fixed and independently approved; the reviewer also
passed 21 focused backend and 5 focused frontend regressions on the final code.
The backend is running locally at `127.0.0.1:8000` and its root health response is Online.
The verified `.next-source-verify` production build is served locally at `localhost:3000`;
reload and sign-up/sign-in navigation passed with no new browser errors after 15:49 UTC.
A development-only first-load `layout.js` syntax error recurred at 15:47 UTC, then reload
worked. The generated file and two later served bodies matched and parsed, including all
30 embedded module bodies; the failed response was not captured and the cause remains
unknown. No source fix is claimed for that development error. Browser checks remain
signed out; no authenticated upload/generation, live provider/cloud transaction or
short-slide/merged-exam quality, latency or cost improvement is claimed from these gates.

## Processing and deployment limits

- Documents, historical exams, tutorials and solution uploads are capped at 100 MiB;
  audio/video uploads and direct media downloads at 512 MiB. Supported platform URL
  metadata is checked for a four-hour duration limit. Saved records use a conservative
  750,000-byte JSON-size check; oversized content is rejected rather than silently cut.
- Lecture preparation accounts for all supported source locations, bounded to 160
  pages/slides and 600,000 extracted characters per file; over-limit or unresolved visual
  sources require split/replace/retry guidance. DOCX uses paragraph/table locations,
  without invented physical page numbers. The provider must accept original images when
  visual reading is needed; unsupported inputs cannot complete preparation.
- Source reading and synthesis requests have character/image/batch budgets. Successful
  coverage does not guarantee every detail appears in an output or that OCR/semantic
  judgments are correct. Schema, citation and factual-support checks have distinct roles;
  real quality, formula/diagram fidelity, latency and cost require evaluation with actual
  selected materials.
- Document work uses a bounded local executor plus durable records, claim-token leases,
  checkpoints and recovery. Guide failure reuses completed preparation; incomplete
  preparation restarts from its preserved original. Failed/legacy jobs require explicit
  retry/upgrade. Audio retains its separate bounded worker lifecycle. Canceling a browser
  request prevents stale UI updates but does not guarantee cancellation of provider work.
- Public hosting needs explicit backend bind/CORS configuration for the intended HTTPS
  frontend and durable storage. Document acceptance requires a durably preserved original;
  other existing upload paths retain their own storage behavior. Missing derived lecture
  artifacts can be restored from a digest-verified preserved original, while a missing
  original requires restore/replace guidance. Local JSON fallback does not supply offline
  authentication or AI providers.
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
