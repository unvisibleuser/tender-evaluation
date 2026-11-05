FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TENDER_ENVIRONMENT=demo \
    TENDER_DATABASE_URL=sqlite:////data/tender.db \
    TENDER_STORAGE_ROOT=/data/storage

WORKDIR /app

# Editable install keeps app code at /app (config resolves alembic.ini relative to the source tree).
COPY pyproject.toml ./
COPY app ./app
COPY rule_engine ./rule_engine
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install -e . \
    && useradd --system --uid 10001 --home-dir /app tender \
    && mkdir -p /data && chown tender /data

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN sed -i 's/\r$//' /usr/local/bin/docker-entrypoint.sh && chmod +x /usr/local/bin/docker-entrypoint.sh

USER tender
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

ENTRYPOINT ["docker-entrypoint.sh"]
# Single worker on purpose: MVP background processing runs in-process threads.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
