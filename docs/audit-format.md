# Audit format

Every guarded decision can be written as one JSON object per line. Records contain request metadata, policy identity, execution status, timings, CUDA-Q version, result summaries, and errors.

Each record also contains:

- `previous_hash`: SHA-256 hash of the preceding record, or 64 zeroes for the first record
- `record_hash`: SHA-256 of the canonical current record before `record_hash` is added

This creates a tamper-evident chain. It does not provide authenticity by itself: a party able to rewrite the entire file can recompute the chain. For stronger provenance, sign the audit head or store it in an external immutable system.

Verify a chain with:

```bash
cudaq-guard audit verify runs/audit.jsonl
```

Target-option keys containing words such as `token`, `password`, `secret`, or `credential` are redacted from audit records. Provider credentials should still be supplied through the provider's documented credential mechanism rather than command-line options.
