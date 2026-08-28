"""Catalog — making a merchant legible to software (MODELLED).

The single source of price and availability truth. Free text is untrusted by
construction; prices are integer minor units; every price change is versioned
so the commit gate can produce an itemised diff.
"""
