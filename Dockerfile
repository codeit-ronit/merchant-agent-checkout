# SENTINEL control plane. Fixture mode by default — no credentials baked in, ever.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir -r requirements.txt

COPY sentinel/ ./sentinel/
COPY config/ ./config/
COPY cassettes/ ./cassettes/
COPY artifacts/ ./artifacts/
COPY corpus/ ./corpus/
COPY evals/ ./evals/
COPY redteam/ ./redteam/

ENV SENTINEL_MODE=fixture
ENV SENTINEL_CASSETTE=replay
EXPOSE 8080

CMD ["python", "-m", "sentinel.api.main"]
