# SENTINEL — Makefile
# Every command runs in FIXTURE mode by default and needs no credentials.
# Test-mode keys only, ever. Never live keys.

PY := .venv/bin/python
# `python -m pytest` (not bare pytest) so the repo root is on sys.path and the
# top-level evals/ and redteam/ packages import cleanly.
PYTEST := .venv/bin/python -m pytest

.DEFAULT_GOAL := help

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Create venv and install dependencies
	python3 -m venv .venv
	$(PY) -m pip install -q -U pip
	$(PY) -m pip install -q -e ".[dev]"

.PHONY: demo
demo: frontend-if-needed ## Start everything in fixture mode (operator surface + API), no keys required
	SENTINEL_MODE=fixture $(PY) -m sentinel.api.main

.PHONY: frontend-if-needed
frontend-if-needed: ## Build the operator surface only if it has not been built
	@test -f frontend/dist/index.html || $(MAKE) frontend

.PHONY: demo-cli
demo-cli: ## Run the headline CLI demonstration: a money-movement denial with a plain-language reason (offline)
	SENTINEL_MODE=fixture $(PY) -m scripts.demo_cli

.PHONY: test
test: ## Tiers 1-3: fast, deterministic, no model
	$(PYTEST) -q -m "tier1 or tier2 or tier3 or critical"

.PHONY: test-all
test-all: ## Run the entire test suite
	$(PYTEST) -q

.PHONY: critical
critical: ## Run only the five load-bearing safety tests
	$(PYTEST) -q -m critical -v

.PHONY: eval
eval: ## Run the golden eval set in replay mode with regression gates (offline, no key)
	SENTINEL_MODE=fixture SENTINEL_CASSETTE=replay $(PY) -m evals.runner

.PHONY: redteam
redteam: ## Run the paired A/B red-team suite in fixture mode (offline, no key)
	# auto mode: the deterministic brains regenerate cassettes offline (no network);
	# red-team cassettes are not committed (they record the guardrails-off leak).
	SENTINEL_MODE=fixture SENTINEL_CASSETTE=auto $(PY) -m redteam.runner

.PHONY: verify-audit
verify-audit: ## Walk and verify the audit hash chain, report first break if any
	$(PY) -m sentinel.audit.verify

.PHONY: check-schemas
check-schemas: ## Fixture-vs-reference tool schema parity (offline; reference was live-captured)
	$(PY) -m sentinel.fixtures.schema_parity

.PHONY: check-schemas-live
check-schemas-live: ## Verify against the REAL razorpay/mcp (needs Docker + rzp_test_ keys in env)
	# export RAZORPAY_KEY_ID=rzp_test_... RAZORPAY_KEY_SECRET=... first.
	# Runs the published image over MCP stdio: tool-surface parity + a live money-movement DENY.
	$(PY) -m scripts.live_check

.PHONY: purity
purity: ## Assert the policy engine performs no I/O (import-graph check)
	$(PYTEST) -q tests/unit/test_policy_purity.py -v

.PHONY: secret-scan
secret-scan: ## Fail if anything resembling a live key is present in the tree or history
	$(PY) -m scripts.secret_scan

.PHONY: reference-manifest
reference-manifest: ## (Phase 0) Regenerate the committed upstream tools/list reference artefact
	$(PY) -m scripts.capture_reference_manifest

.PHONY: frontend
frontend: ## Build the operator surface
	cd frontend && npm install && npm run build

.PHONY: clean
clean: ## Remove local runtime state (ledger, token store, governor counters)
	rm -rf sentinel_state *.db *.db-* .pytest_cache .hypothesis
