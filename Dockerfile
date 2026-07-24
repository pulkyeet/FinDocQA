# Slim static web image for FinDocQA Delta.
#
# Serves pre-built change reports (data/reports/*.html) as static HTML. The
# report pipeline (torch, chromadb, sentence-transformers) is intentionally
# absent: reports are generated offline with `make delta-batch` and baked in via
# the COPY below (data/reports is kept by .dockerignore; raw/chunks/chroma/eval/
# diffs are excluded). Result: a ~200MB image with no runtime model download and
# no runtime secrets.
FROM python:3.11-slim

WORKDIR /app

COPY requirements-web.txt .
RUN pip install --no-cache-dir -r requirements-web.txt

# Application code + baked reports.
COPY src/ ./src/

ENV PORT=8000
EXPOSE 8000

WORKDIR /app/src
CMD ["sh", "-c", "uvicorn web.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
