# Deploying Mudaris to the web

Frontend → **Vercel**. Backend → **Render** (Docker). Database → **Firebase** (already cloud).

The repo is now deploy-ready: `Dockerfile`, `.dockerignore`, and `render.yaml` exist, and the
backend reads host/port, CORS origins, the Arabic font, and Firebase credentials from environment
variables. What's left is dashboard work in **your** accounts (I can't sign in as you).

> **Order matters:** deploy the **backend first** to get its URL, then the frontend, then wire CORS
> and Firebase back to the frontend's URL.

---

## 0. Prerequisites
- GitHub account with this repo (`Conqyy/MudarisKH`) — ✅ done.
- A **Render** account (https://render.com) — free.
- A **Vercel** account (https://vercel.com) — free.
- Your **Firebase service-account JSON** (the local `backend/src/config/firebase-key.json`).

### Prep the Firebase key as one line
Render needs the key as a single-line env var. In PowerShell:
```powershell
Get-Content "backend\src\config\firebase-key.json" -Raw | ConvertTo-Json -Compress | Set-Clipboard
```
That copies a JSON-escaped one-liner to your clipboard. (Or just open the file and remove newlines.)
You'll paste it into `FIREBASE_CREDENTIALS_JSON` in step 1.

---

## 1. Backend → Render

1. Render Dashboard → **New +** → **Blueprint**.
2. Connect the `Conqyy/MudarisKH` repo. Render reads `render.yaml` and proposes the
   **mudaris-backend** web service (Docker, free plan). Click **Apply**.
3. It will prompt for the env vars marked `sync: false`. Set:
   | Key | Value |
   |---|---|
   | `OPENROUTER_API_KEY` | (from your local `backend/.env`) |
   | `GROQ_API_KEY` | (from your local `backend/.env`) |
   | `FIREBASE_CREDENTIALS_JSON` | the one-line JSON from step 0 |
   | `CORS_ALLOW_ORIGINS` | leave blank for now (defaults to `*`); tighten in step 3 |
4. Click **Create / Deploy**. The **first build is slow** (~5–10 min) — it installs TeX Live +
   ffmpeg. Watch the logs; a good boot ends with `Uvicorn running on http://0.0.0.0:<port>` and
   `Successfully connected to Cloud Firebase Firestore Database.`
5. Copy the service URL, e.g. `https://mudaris-backend.onrender.com`.
6. **Smoke test:** open `https://mudaris-backend.onrender.com/` — you should see
   `{"status":"Online", ...}`.

---

## 2. Frontend → Vercel

1. Vercel Dashboard → **Add New… → Project** → import `Conqyy/MudarisKH`.
2. Framework preset: **Next.js** (auto-detected). Root directory: **`/`** (repo root). Leave build
   settings default.
3. **Environment Variables** → add:
   | Key | Value |
   |---|---|
   | `NEXT_PUBLIC_BACKEND_URL` | your Render URL from step 1.5 (no trailing slash) |

   > The `NEXT_PUBLIC_FIREBASE_*` values are already in the committed `.env.local`, so Vercel will
   > inline them at build time — you don't need to re-enter them (but you may, to be explicit).
4. **Deploy.** Copy the resulting URL, e.g. `https://mudaris-kh.vercel.app`.

---

## 3. Wire them together (CORS)

1. Back in **Render** → mudaris-backend → **Environment** → set:
   | Key | Value |
   |---|---|
   | `CORS_ALLOW_ORIGINS` | your Vercel URL, e.g. `https://mudaris-kh.vercel.app` |
   Save → Render redeploys automatically.
   (You can list several, comma-separated, incl. Vercel preview URLs.)

---

## 4. Firebase — authorize the frontend domain

Google/email sign-in will be **rejected** until the Vercel domain is allow-listed.

1. Firebase Console → your project (`mudariskh-e74a3`) → **Authentication** → **Settings** →
   **Authorized domains** → **Add domain**.
2. Add your Vercel domain, e.g. `mudaris-kh.vercel.app` (and any custom domain later).

---

## 5. Verify end-to-end
1. Open the Vercel URL, sign up / sign in (confirms Firebase auth + authorized domain).
2. Create a course, upload a lecture doc (confirms frontend → Render backend + Firestore write).
3. Generate a summary or exam (confirms the LaTeX toolchain in the Docker image).
4. Upload a short audio clip (confirms ffmpeg + XeLaTeX + the **Amiri** Arabic font).

---

## Known limitations & gotchas (free tier)

- **Ephemeral storage.** `backend/uploads/` is wiped on every restart/deploy, and Render free
  services **sleep after ~15 min idle** (first request after that takes ~50s to wake). Uploaded
  files and generated PDFs won't survive a restart. Firestore data (courses, summaries metadata,
  chats) persists fine. → To fix, upgrade Render to **Starter** and add a `disk:` in `render.yaml`
  mounted at `/app/backend/uploads`, or migrate file storage to Firebase Storage.
- **Cold-start timeouts.** A long exam generation right after a cold start may feel slow; retry if
  the first request times out while the service wakes.
- **Missing LaTeX packages.** MiKTeX auto-installs packages on your Windows machine; TeX Live in the
  container does **not**. If a generated PDF fails with a missing `.sty`, add the providing
  `texlive-*` package to the `Dockerfile` and redeploy. (The current set covers the common cases.)
- **YouTube ingestion** (`yt-dlp`) can be rate-limited from cloud IPs; file upload is more reliable.

## Security notes
- Secrets (`OPENROUTER_API_KEY`, `GROQ_API_KEY`, the Firebase key) live **only** in Render's env
  store — they are gitignored and excluded from the Docker image via `.dockerignore`. Keep it that way.
- The `NEXT_PUBLIC_FIREBASE_*` web config is not secret (it's a client identifier), so committing it
  in `.env.local` is fine. Firestore security rules (`firestore.rules`) enforce per-user isolation.
