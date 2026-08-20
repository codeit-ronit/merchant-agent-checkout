"""The control-plane API (FastAPI). REST + SSE over the same trace stream the
eval harness consumes. All data leaves the API pre-redacted — the frontend never
redacts, because redaction in the client means the real value already crossed the
wire.
"""
