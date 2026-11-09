# Mudaris — AI Study & Exam Engine

Mudaris helps university students study from their own course materials. It combines
lecture documents, past exams, tutorials, recordings and typed notes to create practice
exams, flashcards, summaries and a course-grounded AI tutor. It was built for students at
Imam Mohammad Ibn Saud Islamic University.

## Study workflow

1. **Create a course and upload its lecture documents** (PDF, PPTX or DOCX).
2. **Wait for both automatic stages:** *Preparing document* preserves the original and
   prepares its text, images and source locations; *Creating lightweight analysis* builds
   an academic guide. Both stages are mandatory. Retry a failed stage from the course page.
3. **Select “I've uploaded all lecture documents.”** Every lecture must finish both stages
   before the course can be confirmed. Past exams, tutorials, recordings, notes and new
   study-tool requests stay locked until confirmation. Adding, deleting, replacing or
   retrying a lecture requires confirming the completed document set again.
4. **Add supporting material and inspect its analysis report.** Upload past papers,
   tutorial sheets, audio/video recordings, supported media URLs or typed notes. Upload
   acceptance starts background work; wait for preparation and analysis to finish. Choose
   **Quiz, Midterm or Final** for each past-exam upload; this owner-selected type is retained
   for every paper in a merged PDF.
5. **Choose your sources and study.** Select the lecture documents that define your scope,
   then the supporting materials to use. Generate an exam, flashcards or summary, or open
   the tutor. Existing saved outputs remain accessible while a course needs confirmation.

Older uploads need explicit preparation from their saved originals before they can be
used for new generation. Missing originals must be restored or replaced.
Older past exams without a type also need explicit classification from the course page.
Classification preserves their original files, analysis and saved source references.

## Study tools

| Tool | What it does |
| --- | --- |
| **AI tutor** | Answers course questions using selected original lecture evidence, checked supporting material and saved conversation history. Academic replies include source references. |
| **Practice exams** | Generates one predicted Quiz, Midterm or Final with your requested total marks, using patterns across all selected historical papers. Solve it yourself, then reveal a PDF model-answer key with answers in red. You can attach your own solved paper for comparison. |
| **Flashcards** | Generates up to 20 cards from selected material, including important concepts, professor emphasis and tutorial-solving methods. |
| **Summaries** | Produces notes whose length follows relevant content, complexity, importance and your instructions. There are no fixed page, section or term quotas; course administration and textbook lists are omitted by default. |
| **Weekly calendar** | Organizes Sunday–Thursday lectures with times, hall notes and conflict checks. |

The interface supports English and Najdi Arabic with RTL layout, saved language/sidebar
preferences and a light theme. Some workflow labels use English fallback. Course content
keeps its own language. Source previews, saved chats and PDF exports are available within
the relevant study tools.

## How evidence is used

**Original lectures define academic scope.** Their automatic guides help agents find
material; they are not a replacement for the originals or a whitelist of permitted
concepts. Agents read source text and images, including definitions, formulas and diagrams.
Generation requires at least one selected prepared lecture. The tutor uses the confirmed
lecture foundation when no lecture documents are selected.

**Supporting material is checked against that scope.** The shared analysis pipeline
preserves originals, inventories their content and records what the lectures support:

| Material | Analysis |
| --- | --- |
| **Past exams** | Inventories questions, subparts, topics and required shared context. Each requirement is checked individually; one covered subpart does not certify a whole question. Merged uploads retain separate paper identities. |
| **Tutorials** | Checks practice questions and solving methods against the lectures. Tutorials can contribute problem ideas, but do not determine exam marks or question-type proportions. |
| **Recordings** | Transcribes through Groq, then checks teaching points, examples, emphasis and exam hints against lecture evidence. Available timestamps refer to actual transcript segments. |
| **Typed notes** | Preserves the submitted text and checks it as student-reported material. Notes are not treated as a verbatim professor recording. |

Reports distinguish lecture-supported material, related supplementary teaching, content
outside the selected scope, content not found, unresolved review and conflicts. An
incomplete search does not establish that a topic is outside the course. Narrowing the
lecture selection rechecks supporting material against that selection.

Tutorial matches point to lecture documents and source locations. The report does not
currently provide a separate overview of chapter names covered by a tutorial.

**All generators use checked source evidence.** Exam, flashcard and summary requests read
selected lecture units in bounded batches and use eligible supporting evidence. Exams and
flashcards require lecture-supported knowledge; summaries and tutoring can include clearly
attributed supplementary teaching anchored to a selected lecture. Output checks reread
cited originals, including exam shared context and answer rubrics.

**Past papers contribute to one exam blueprint.** Detected papers contribute normalized
evidence equally, independently of upload order. Their question types and typical counts
inform one new paper; counts are not summed into an oversized exam. The requested mark
total determines the new exam's marks. Topic emphasis is a study signal, not a calibrated
probability of future exam coverage. Unclear paper boundaries require review or splitting.

**Past exams are separated by type.** Quizzes, Midterms and Finals use the database
collections `historical_quizzes`, `historical_midterms` and `historical_finals`. The original
analysis pipeline is shared. Exam generation uses an explicit type independently of total
marks; summaries have their own past-exam type selector. Both workflows query only that
category before checking readiness or building model context, and reject IDs from other
categories. You can select individual papers within the chosen type or deselect them all.
Model-detected paper labels do not override the upload type.

**Sources remain versioned.** Citations open the exact owned source version and location.
They never silently open replacement content. Selected material that is unavailable,
stale or unfinished produces actionable guidance. A source change during generation can
reject publication of the result. Saved exam repair uses the exam's saved evidence and
preserves its questions and official answers.

At the API, omitted or `null` source-ID lists select all owned material of that category;
`[]` excludes it. Exam, summary and flashcard generation require a nonempty lecture
selection. The tutor instead falls back to the confirmed foundation for omitted or empty
lecture selections. Invalid explicit IDs are rejected.
For exam and summary requests, `historical_exam_type` scopes these past-exam ID rules to
one of `quiz`, `midterm` or `final`. Older exam clients derive it from a recognized
`exam_type`; generic/custom labels and older summary clients default to `final`.
An omitted category never widens these requests to all three types.

## Architecture

| Layer | Implementation |
| --- | --- |
| Frontend | Next.js App Router, React, TypeScript, Tailwind CSS and Firebase client SDK |
| Backend | FastAPI and Uvicorn with Firebase Admin SDK |
| AI | OpenRouter model configured by `OPENROUTER_MODEL`; Groq-hosted Whisper for transcription |
| Source processing | PDF, PowerPoint and Word extraction with original text/image locations; durable preparation and supporting-analysis jobs |
| Data and files | Firestore records, private Firebase Storage artifacts and local files under `backend/uploads/` |
| PDFs and media | `pdflatex` / `xelatex` for PDFs; ffmpeg and yt-dlp for media handling |

The Python agent modules cover document processing, audio intelligence, historical exams,
exam/flashcard generation, summaries and tutoring. They run inside the backend process.
Shared source services and the supporting-material pipeline supply evidence; API/workers
persist results through `FirebaseClient`.

```text
src/
  app/                     Course pages, dashboard, authentication and study tools
  components/              Uploads, source viewers, reports and shared UI
  lib/                     API, authentication, source selection and UI state
backend/
  src/api.py               FastAPI routes
  src/agents/              Analysis, generation and tutor modules
  src/config/              Settings and prompts
  src/services/            Lecture preparation, source library and evidence reader
  src/supporting/          Supporting originals, jobs, inventories and alignment
  src/database/            Firebase persistence and publication checks
  src/utils/               Contracts, storage, media, exam blueprints and PDFs
  tests/                   Backend regression tests
  requirements.lock.txt    Pinned application and test dependencies
tests/frontend/            Vitest and React regression tests
firebase.json              Firestore configuration
firestore.rules            Client access rules
```

## Local setup

### Requirements

- Python **3.12**, matching the checked-in dependency lock.
- Node.js **20.19+ within Node 20**, **22.12+ within Node 22**, or **24+**, as declared in `package.json`.
- A TeX distribution such as MiKTeX, with `pdflatex` and `xelatex` on `PATH`, for PDF output.
- ffmpeg on `PATH` for audio/video processing.
- A Firebase project with Authentication, Firestore and a Storage bucket, plus a service
  account permitted to access them. Cloud-backed source ingestion requires successful
  private Storage writes.
- An OpenRouter API key and access to the configured model. Use a model that accepts
  images when the source material requires visual reading.
- A Groq API key for recording transcription. Typed notes do not require transcription.

### 1. Configure and run the backend

From the repository root in PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `backend/.env` using `backend/.env.example` as the template:

| Setting | Purpose |
| --- | --- |
| `OPENROUTER_API_KEY` | Backend credential for analysis, generation and tutoring |
| `OPENROUTER_MODEL` | OpenRouter model ID; the template specifies the repository default |
| `OPENROUTER_BASE_URL` / `OPENROUTER_MAX_TOKENS` | Provider endpoint and default output-token budget |
| `FIREBASE_KEY_PATH` | Service-account JSON path; default: `src/config/firebase-key.json` |
| `STORAGE_BUCKET` | Your Firebase Storage bucket name |
| `GROQ_API_KEY` / `GROQ_WHISPER_MODEL` | Transcription credential and model |
| `WHISPER_LANGUAGE` | Optional language code; leave empty for automatic detection |
| `MUDARIS_RELOAD` | Leave `0` for normal use so code reloads do not interrupt background work |

Place your service-account JSON at `backend/src/config/firebase-key.json`, or set
`FIREBASE_KEY_PATH` to its location. Then, from `backend/`:

```powershell
.\.venv\Scripts\python.exe -m src.api
```

The backend listens at [http://127.0.0.1:8000](http://127.0.0.1:8000).
Interactive endpoint schemas are at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).
Start it from `backend/` so environment loading and the relative credential path agree.

On macOS/Linux, use `.venv/bin/python` in place of `.\.venv\Scripts\python.exe` and copy
`.env.example` to `.env` only if `.env` does not already exist.

### 2. Configure and run the frontend

The root `.env.local` is deliberately tracked and contains public frontend configuration.
For your own Firebase project, replace its values with your project's web configuration:

```dotenv
NEXT_PUBLIC_FIREBASE_API_KEY=your-web-api-key
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=your-project
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=your-bucket.firebasestorage.app
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=your-sender-id
NEXT_PUBLIC_FIREBASE_APP_ID=your-app-id
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
```

Use the same Firebase project as the backend. Enable Email/Password and any desired
Google sign-in provider, and authorize `localhost` in Firebase Authentication.

In a second terminal, from the repository root:

```powershell
npm ci
npm run dev
```

Open [http://localhost:3000](http://localhost:3000) and sign in.

### 3. Apply Firestore rules

From the repository root, using an authenticated Firebase CLI:

```powershell
firebase deploy --only firestore:rules --project YOUR_PROJECT_ID
```

`firebase.json` points to `firestore.rules`. Deploy to the intended project before relying
on these client restrictions. Pushing Git commits does not deploy Firebase rules.

**Credential responsibilities:** `backend/.env` and the service-account JSON are ignored
by Git and must be supplied locally. Keep OpenRouter/Groq keys and service-account secrets
there; never put them in `NEXT_PUBLIC_*` variables or the tracked frontend env file.
Firebase web configuration is public client configuration, not an authorization boundary.
The backend verifies Firebase ID tokens and ownership; deployed rules control client access.

## Development checks

After installing frontend and backend dependencies, run from the repository root:

```powershell
npm test
npm run lint
npx tsc --noEmit --incremental false
npm run build
.\backend\.venv\Scripts\python.exe -m pytest backend/tests -q
```

Use `backend/.venv/bin/python` for the backend test command on macOS/Linux. To isolate build output,
set `NEXT_BUILD_DIR=.next-verify` in your shell before building and starting Next.js.

Regression tests cover source preparation, selection, alignment, generation contracts,
versioned citations, background jobs and UI lifecycles. Provider calls are stubbed in the
regression suite; environment-dependent cloud checks can be skipped. These checks do not
establish live model accuracy or an authenticated end-to-end flow. Validate real uploads,
merged papers, source previews and generated PDFs with your configured services.

## API and operational notes

- Data endpoints require `Authorization: Bearer <Firebase ID token>`. Upload routes return
  **202 Accepted** for background work; use document detail and supporting status/report
  endpoints to follow progress. See the local API docs for request schemas.
- Past-exam uploads require multipart `exam_type`. Lists accept `?exam_type=quiz` (or
  `midterm`/`final`); an unfiltered course overview includes all types and legacy uploads.
  `POST /api/historical-exams/{id}/classify` accepts `{"exam_type":"quiz"}` to classify an
  owned legacy upload. A previously assigned type cannot be changed through this endpoint.
- The course foundation endpoints expose readiness and confirmation. Both the interface
  and API enforce the lecture prerequisite, including retries and recovered jobs.
- Original files and source previews are served through authenticated routes. New cloud
  uploads are private; existing public object ACLs/download tokens need separate cleanup.
- Course/account deletion cleans up owned materials, generated outputs, chats and schedules.
  Account deletion requires recent authentication; retry failed cleanup while signed in.
- Saved exam detail does not start AI repair. Valid cached answer keys and complete saved
  rubrics can render while a course is locked. New AI repair/explanations require the saved
  evidence and current confirmation. Exam PDF routes use the saved document ID (`doc_id`).
- Document, past-exam, tutorial and solution uploads are capped at **100 MiB**; audio/video
  files and direct media downloads at **512 MiB**. Document processing is bounded to **160
  pages/slides** and **600,000 extracted characters** per file. Unresolved coverage and
  exhausted budgets produce split/replace/retry guidance instead of silent truncation.
- The default server binds to loopback and allows localhost frontend origins. Public
  hosting requires explicit backend bind/CORS configuration and durable storage. Local
  JSON fallback does not provide offline Firebase authentication or AI services.
- AI quality, processing time and cost depend on actual sources and provider behavior.
  Citation and factual-support checks help trace answers, but cannot guarantee perfect
  extraction, diagram understanding or exam predictions. TeX processing has safeguards;
  it is not an operating-system sandbox.
