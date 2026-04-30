# TrustCrawler — single-image, two-process container (FastAPI + Streamlit).
# CLAUDE.md §8 / plan.txt P8.

FROM python:3.11-slim AS base

WORKDIR /app

# build-essential is needed for some wheels that don't ship a pre-built one
# (notably trafilatura's lxml dependency on slim). curl stays for healthchecks
# in compose / smoke tests; it's tiny.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install CPU-only torch first. sentence-transformers brings in torch as a
# transitive dep, and on Linux that pulls the CUDA wheels by default — ~5 GB
# of GPU runtime we don't need. Pinning the CPU index here means the second
# `pip install` sees torch already satisfied and skips the GPU stack.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache the sentence-transformers backbone so KeyBERT works the first time
# without reaching out to Hugging Face. Runs into the default HF cache under
# /root/.cache/huggingface/, which is part of the image layer. Adds ~90 MB
# but removes a hard runtime network dependency. CLAUDE.md §8 / §14.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Pre-cache the tiktoken encoder used by both chunkers. Tiny (~3 MB) but
# saves the first-run download under tiktoken's openai bucket.
RUN python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')"

COPY . .

# When .env is bind-mounted into /app at runtime (compose does this by
# default; raw `docker run` typically uses --env-file at the docker layer),
# uvicorn loads it via --env-file in run.sh. See run.sh for the full story.

EXPOSE 8000 8501

# Bash (not sh) — we use the bash-only `wait -n` for fast shutdown.
CMD ["bash", "run.sh"]
