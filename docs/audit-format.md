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

Writers hold a shared lock across verification of the existing chain, construction of the next record, append, and `fsync`. Readers and verifiers use the same lock, so cooperating threads and processes cannot observe another writer's partial record. The persistent `runs/audit.jsonl.lock` sidecar must remain present while the log is in use; removing or replacing it defeats coordination. Verification requires permission to open or create that sidecar. Locks use the operating system's file-locking support on Linux/macOS and Windows; network filesystems must provide equivalent locking semantics.

Interrupted and short writes are retried. Every record must end in a newline. A failed append can still leave an incomplete tail; subsequent verification and appends reject it and preserve the damaged file for investigation. There is no automatic truncation or repair. Existing newline-terminated chains retain the same format and hashes. Full-chain verification remains necessary on append, so total append work grows quadratically with the number of records in a single log.

To verify an exported log on read-only media, copy the completed log into a writable directory first so verification can create its sidecar. Preserve the original export unchanged.

Before configuring an allowed workload, `Guard` checks the existing chain and append access. This prevents work from starting with an already damaged or inaccessible audit file. It cannot guarantee the final append after execution if the disk fills, the process dies, or permissions change. Configure, resource-probe, and workload exceptions are audited when the log remains writable; resource-policy denials produce one `denied_resource` record.

Result summaries recognise non-empty bitstring-to-integer histograms as samples. Ordinary mappings, including energy and iteration values, remain mappings without integer conversion or fabricated shot totals.

Target-option keys containing words such as `token`, `password`, `secret`, or `credential` are redacted from audit records. Provider credentials should still be supplied through the provider's documented credential mechanism rather than command-line options.
