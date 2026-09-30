# syntax=docker/dockerfile:1

# ---- Stage 1: build the React frontend ------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python API + static UI -----------------------------------------------
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Bake the multilingual embedding model into the image so the running container
# needs no network access for retrieval. If the download fails (e.g. Hugging Face
# is unreachable), the build continues and the app falls back to BM25-only
# retrieval. In mainland China, pass --build-arg HF_ENDPOINT=https://hf-mirror.com
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ARG HF_ENDPOINT=https://huggingface.co
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    FASTEMBED_CACHE_PATH=/app/models
RUN mkdir -p /app/models && \
    ( HF_ENDPOINT=${HF_ENDPOINT} python -c "import os; from fastembed import TextEmbedding; TextEmbedding(os.environ['EMBEDDING_MODEL'], cache_dir=os.environ['FASTEMBED_CACHE_PATH'])" \
      || echo "WARNING: could not download ${EMBEDDING_MODEL}; InsureTutor will use BM25-only retrieval" )

COPY backend/ backend/
COPY data/ data/
COPY --from=web /web/dist static/

ENV DATA_DIR=/app/data \
    VAR_DIR=/app/var \
    STATIC_DIR=/app/static \
    HF_HUB_OFFLINE=1

# Pre-build the chunk + embedding index (seeds the named volume on first run).
WORKDIR /app/backend
RUN python -m app.warmup

RUN useradd --create-home --uid 10001 insuretutor && chown -R insuretutor /app/var /app/models
USER insuretutor

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request, sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status != 200)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
