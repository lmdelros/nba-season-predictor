# Image for the data pipeline (ingestion, features, models, simulation), with the full
# Python dependencies. The API has its own slim image in api/Dockerfile.
#   docker compose run --rm pipeline python -m scripts.seed_demo
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt requirements-api.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY ingestion/ ingestion/
COPY features/ features/
COPY models/ models/
COPY simulation/ simulation/
COPY evaluation/ evaluation/
COPY scripts/ scripts/

RUN useradd --create-home --uid 1000 appuser
USER appuser

CMD ["python", "-m", "scripts.seed_demo"]
