FROM python:3.11-slim

# FIX v3-hauts: durcissement container
#  - user non-root
#  - deps systeme minimales
#  - pas de cache pip
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -m -u 1000 appuser

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip==24.2 \
    && pip install --no-cache-dir -r requirements.txt

COPY app ./app
# Repertoire pour les modeles (volume monte en prod)
RUN mkdir -p /app/models && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
