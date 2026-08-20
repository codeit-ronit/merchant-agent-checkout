# Reason code: fraud (unauthorised transaction)
The cardholder claims they did not authorise the transaction.
## Required evidence
- Proof the cardholder was authenticated (3DS / OTP verification record).
- Device fingerprint or IP address matching the cardholder history.
- Delivery confirmation to the cardholder billing address.
- Prior undisputed transactions from the same card/customer.
## Notes
Strong 3DS authentication is the single most persuasive item; without it, fraud
disputes are usually lost.
