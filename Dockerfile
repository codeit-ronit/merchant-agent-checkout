# SENTINEL — production image. Multi-stage: Node builds the operator surface,
# Python serves the control plane + the built SPA. Fixture mode, no credentials
# baked in, ever. Binds to $PORT (Render/Railway/Fly) or 8080 locally.

# ---- stage 1: build the React operator surface ----
FROM node:20-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build      # -> /fe/dist

# ---- stage 2: python runtime ----
FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml requirements.txt ./
RUN pip install --no-cache-dir -e . || pip install --no-cache-dir -r requirements.txt

# application + the data the six views read (all synthetic, committed)
COPY sentinel/ ./sentinel/
COPY config/ ./config/
COPY cassettes/evals/ ./cassettes/evals/
COPY artifacts/ ./artifacts/
COPY corpus/ ./corpus/
COPY evals/ ./evals/
COPY redteam/ ./redteam/
COPY scripts/ ./scripts/
# the built SPA from stage 1 (served at / by FastAPI)
COPY --from=frontend /fe/dist ./frontend/dist

ENV SENTINEL_MODE=fixture
ENV SENTINEL_CASSETTE=replay
EXPOSE 8080
CMD ["python", "-m", "sentinel.api.main"]
