FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
RUN useradd --create-home --uid 1000 app && mkdir -p /data /models && chown app:app /data /models

COPY requirements.txt .
RUN pip install -r requirements.txt

USER app

# Download the embedding model while building, so the first start is quick and works offline.
ARG EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
ENV EMBEDDING_CACHE_DIR=/models
RUN python -c "import sys; from fastembed import TextEmbedding; TextEmbedding(sys.argv[1], cache_dir='/models')" "$EMBEDDING_MODEL"

COPY --chown=app:app app ./app
COPY --chown=app:app static ./static
COPY --chown=app:app samples ./samples
COPY --chown=app:app scripts ./scripts
COPY --chown=app:app eval ./eval

ENV DATA_DIR=/data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=180s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
