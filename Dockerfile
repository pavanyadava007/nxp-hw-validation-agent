# hwval demo image -- runs the Streamlit UI. Built on requirements.txt only
# (no TensorFlow) to keep the image lean; hwval.ml degrades to the PCA
# autoencoder fallback, exactly as it does on Streamlit Community Cloud.
FROM python:3.11-slim

LABEL org.opencontainers.image.title="hwval" \
      org.opencontainers.image.description="AI-driven hardware validation & reporting agent (Streamlit demo)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    TF_CPP_MIN_LOG_LEVEL=3 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System deps: libpq for psycopg2-binary's runtime linkage, curl for the
# healthcheck. DejaVu fonts keep matplotlib figures from falling back to a
# missing-glyph placeholder font -- a few MB, worth it for report quality.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY src ./src
COPY app ./app
COPY .streamlit ./.streamlit
COPY pyproject.toml ./

# Non-root user; own /app (writable for artifacts/) plus the venv site-packages
# are already owned by root but readable, which is all a running container needs.
RUN useradd --create-home --uid 1000 hwval \
    && mkdir -p /app/artifacts \
    && chown -R hwval:hwval /app
USER hwval

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["streamlit", "run", "app/streamlit_app.py", \
            "--server.address=0.0.0.0", "--server.port=8501", \
            "--server.headless=true"]
