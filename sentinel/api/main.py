"""FastAPI control-plane API. Run: `make demo` (SENTINEL_MODE=fixture).

Serves the six operator views' data over REST + an SSE trace stream, and the
built React frontend from frontend/dist when present. Offline, no credentials.
"""

from __future__ import annotations

import asyncio
import json
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sentinel.api.service import ControlPlane
from sentinel.common.config import repo_root

app = FastAPI(title="SENTINEL control plane", version="0.1.0")

# CONDUIT commerce surface (catalog / mandates / purchase+SSE / orders) — the
# one-line mount is the whole SENTINEL-side change (ADR-031 layering).
from conduit.api import router as _commerce_router  # noqa: E402
app.include_router(_commerce_router)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
cp = ControlPlane()


@app.get("/api/health")
def health():
    return {"status": "ok", "mode": "fixture", "note": "test mode only; not affiliated with Razorpay"}


@app.get("/api/policies")
def policies():
    return cp.list_policies()


@app.get("/api/policies/{policy_id}/source")
def policy_source(policy_id: str):
    return {"id": policy_id, "source": cp.policy_source(policy_id)}


@app.get("/api/scenarios")
def scenarios():
    return cp.scenarios()


class RunReq(BaseModel):
    scenario_id: str
    auto_approve: bool = False


@app.post("/api/runs")
def create_run(req: RunReq):
    return cp.run_scenario(req.scenario_id, auto_approve=req.auto_approve)


@app.get("/api/runs")
def list_runs():
    return cp.list_runs()


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    r = cp.get_run(run_id)
    return r or JSONResponse({"error": "not found"}, status_code=404)


@app.get("/api/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """SSE: replays a completed run's trace event by event so the Run console can
    render it as a live stream. Sequence numbers let a reconnecting client
    backfill without gaps."""
    from sse_starlette.sse import EventSourceResponse
    run = cp.get_run(run_id)

    async def gen():
        if not run:
            yield {"event": "error", "data": json.dumps({"error": "unknown run"})}
            return
        for evt in run["trace"]:
            yield {"event": "trace", "data": json.dumps(evt)}
            await asyncio.sleep(0.15)   # paced so the UI reads as live
        yield {"event": "done", "data": json.dumps({"run_id": run_id})}

    return EventSourceResponse(gen())


@app.get("/api/approvals")
def approvals():
    return cp.pending_approvals()


class ResolveReq(BaseModel):
    approve: bool
    note: str | None = None


@app.post("/api/approvals/{approval_id}")
def resolve_approval(approval_id: str, req: ResolveReq):
    return cp.resolve_approval(approval_id, req.approve, req.note, now_ms=int(time.time() * 1000))


@app.get("/api/audit")
def audit():
    return cp.audit_entries()


@app.get("/api/audit/verify")
def audit_verify():
    return cp.verify_audit()


@app.get("/api/evals")
def evals():
    return cp.eval_report()


@app.get("/api/redteam")
def redteam():
    return cp.redteam_report()


@app.get("/api/live")
def live():
    return cp.live_report()


class DryRunReq(BaseModel):
    candidate_policy_id: str
    run_id: str


@app.post("/api/policies/dry-run")
def dry_run(req: DryRunReq):
    return cp.dry_run(req.candidate_policy_id, req.run_id)


# --- serve the built frontend if present ---
_dist = repo_root() / "frontend" / "dist"
if _dist.is_dir():
    from fastapi.staticfiles import StaticFiles
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="frontend")


def main():
    import os

    import uvicorn
    # Hosts (Render/Railway/Fly) inject $PORT; default 8080 for local `make demo`.
    port = int(os.environ.get("PORT", "8080"))
    print(f"SENTINEL control plane on http://0.0.0.0:{port}  (fixture mode, no credentials)")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    main()
