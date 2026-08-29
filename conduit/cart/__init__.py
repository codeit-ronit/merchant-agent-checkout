"""Cart — the mutable object the agent reasons over (MODELLED, off-rail).

The agent names WHAT (item ids, quantities); code produces HOW MUCH, from
live catalog truth, on every mutation. The cart never stores a price the
agent supplied, and there is exactly one moment where thinking becomes
commitment: the gate.
"""
