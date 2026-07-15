# ── Mudaris backend image ─────────────────────────────────────────────────
# FastAPI + the full PDF/audio toolchain the app shells out to:
#   • pdflatex  (exams, summaries)      → texlive-latex-*
#   • xelatex   (audio-analysis PDFs)   → texlive-xetex + texlive-lang-arabic
#   • ffmpeg    (audio/video decoding)
#   • Amiri     (Arabic TTF for XeLaTeX; replaces the Windows-only "Arial")
#
# Build context is the REPO ROOT (see render.yaml / .dockerignore).
FROM python:3.11-slim

# System toolchain. TeX Live packages are pinned to a pragmatic-but-not-huge
# set. NOTE: unlike MiKTeX on Windows, TeX Live does NOT auto-install missing
# packages at compile time — if a generated document needs a .sty that isn't
# here, add the providing texlive-* package below and redeploy.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    fontconfig \
    fonts-hosny-amiri \
    latexmk \
    texlive-latex-base \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-xetex \
    texlive-lang-arabic \
    texlive-plain-generic \
  && fc-cache -f \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app/backend

# Install Python deps first so the layer caches across code changes.
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# App code (secrets are NOT copied — see .dockerignore; they come from env vars).
COPY backend/ ./

# Defaults for the cloud runtime. $PORT is injected by Render at run time and
# read by src/api.py; HOST must be 0.0.0.0 to accept external connections.
ENV HOST=0.0.0.0 \
    AUDIO_ARABIC_FONT=Amiri \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# src/api.py's __main__ reads $HOST/$PORT and starts uvicorn.
CMD ["python", "-m", "src.api"]
