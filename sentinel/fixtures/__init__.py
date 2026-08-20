"""The fixture world: a deterministic in-process double of the upstream Razorpay
MCP server, plus the synthetic data generators that back it.

The fixture exists so evaluations are deterministic and the red-team suite never
touches anyone's infrastructure. Its tool schemas must match upstream exactly,
or evals pass against fixtures and fail against reality.
"""
