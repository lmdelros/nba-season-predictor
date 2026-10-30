# REST API image. Build from the repo root so requirements-api.txt is in the context:
#   docker build -f api/Dockerfile -t nba-predictor-api .
FROM python:3.12-slim

# No .pyc files in the image, and log lines appear immediately instead of buffered.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first: this layer stays cached until requirements-api.txt changes,
# so code-only changes rebuild in seconds.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY api/ api/

# Run as an unprivileged user rather than root.
RUN useradd --create-home --uid 1000 appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
