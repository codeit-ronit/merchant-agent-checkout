"""The SENTINEL MCP proxy — layer 1, the enforcement guarantee.

Presents itself to the agent as the tool provider and acts as an MCP client to
the real upstream. Its one job is to run the decision pipeline on every
``tools/call`` and post-process every result. It decides no policy itself (that
is the Policy Engine), stores no audit records (that is the Ledger), and knows
nothing about specific agents, models, or providers.
"""
