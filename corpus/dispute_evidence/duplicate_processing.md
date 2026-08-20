# Reason code: duplicate_processing
The customer claims they were charged more than once for the same purchase.
## Required evidence
- The two transaction records with their distinct order ids and timestamps.
- Proof the charges correspond to two separate purchases (distinct carts/items).
- Refund record if one of the charges was already refunded.
## Notes
If the two charges share an order id and amount within a short window, the
dispute is likely valid and should be conceded, not contested.
