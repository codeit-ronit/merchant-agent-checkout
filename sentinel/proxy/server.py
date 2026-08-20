"""SENTINEL MCP proxy — the enforcement boundary presented as a server.

It filters the upstream manifest (FORBIDDEN and UNKNOWN tools are removed so they
never enter a model's context) and annotates the survivors with their risk class
(honest information about what the model is holding). Every ``call`` runs the
interceptor's decision pipeline.

The point of building this as a server rather than a function the agent imports
is the framework-independence claim: ANY MCP client pointed at it is subject to
identical policy. That is the property a prompt can never have — and the
``test_framework_independence`` test drives this with a client that is not the
agent loop, proving the boundary holds regardless of caller.

A production deployment wraps this in an MCP stdio/HTTP transport (the official
``mcp`` SDK); the enforcement logic is transport-agnostic and lives here.
"""

from __future__ import annotations

from sentinel.contracts.decision import InjectedEnv
from sentinel.proxy.classifier import ReconciliationReport, descriptor_index, reconcile
from sentinel.proxy.interceptor import Interceptor, InterceptOutcome, Signals


class SentinelProxyServer:
    def __init__(self, *, upstream, interceptor: Interceptor):
        self.upstream = upstream
        self.interceptor = interceptor
        self._report: ReconciliationReport = reconcile(upstream.list_tools())
        self._descriptors = descriptor_index(self._report)

    @property
    def reconciliation(self) -> ReconciliationReport:
        return self._report

    def list_tools(self) -> list[dict]:
        """The manifest the model sees: FORBIDDEN + UNKNOWN removed, survivors
        annotated with their risk class."""
        out = []
        for d in self._report.callable_manifest:
            out.append({
                "name": d.name,
                "description": f"[{d.risk_class.value}] {d.description}",
                "inputSchema": d.input_schema,
            })
        return out

    def call(self, tool_name: str, arguments: dict, *, env: InjectedEnv, signals: Signals,
             step_id: str, call_id: str) -> InterceptOutcome:
        descriptor = self._descriptors.get(tool_name)
        if descriptor is None:
            # a name not in the manifest at all -> synthesise an UNKNOWN descriptor
            from sentinel.contracts.enums import ClassificationStatus, RiskClass
            from sentinel.contracts.tools import ToolDescriptor
            descriptor = ToolDescriptor(name=tool_name, upstream_name=tool_name,
                                        risk_class=RiskClass.UNKNOWN,
                                        classification_status=ClassificationStatus.UNCLASSIFIED)
        return self.interceptor.handle_call(descriptor, arguments, env, signals, step_id, call_id)
