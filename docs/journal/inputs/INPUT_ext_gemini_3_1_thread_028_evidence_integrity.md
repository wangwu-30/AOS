# [INPUT] THREAD-028: Evidence Integrity & Non-Repudiation

- **id**: 20260226-THREAD-028-PROPOSAL-GEMINI
- **author**: ext_gemini_3_1
- **topic**: Evidence Integrity (Kernel-level Signing)
- **position**: Propose mandatory Kernel-side signing for all Evidence blobs to prevent tampering in Local/Remote transit.

## evidence
1.  **Current State**: [evidence_store.py](file:///Users/wangwu/codex/agentos-next/src/agentos_next/kernel/evidence_store.py) stores raw JSON/blobs without cryptographic verification.
2.  **Report Insight**: *deep-research-report.md* (Line 51/140) highlights seL4 and CHERI as benchmarks for high-assurance isolation and verifiable paths.
3.  **Risk**: In a multi-tenant or remote executor scenario, evidence can be altered before auditing, breaking the "Truth Source" invariant.

## tradeoffs
- **Security vs Latency**: Signing every tool I/O event adds milliseconds. MUST use asynchronous signing or batching for high-frequency tool calls.
- **Key Management Complexity**: Storing Kernel private keys securely (HSM or Secure Enclave) adds deployment friction for local users.

## open_questions
- Should we use Ed25519 (Fast, small signatures) or a TPM-backed approach for local execution?
- Do we sign individual Evidence chunks or the entire Trace session at `TURN_FINISHED`?

## proposal
### Bounded Spike: Kernel Evidence Signer
1.  Initialize a transient (or persistent) Ed25519 keypair for the Kernel.
2.  Append a `signature` field to `EvidenceRef` in `agentos_next/kernel/types.py`.
3.  Modify `EvidenceStore.put` to sign the hash of the content before writing.

## acceptance
- `verify_evidence(trace_id)` returns `true` for all valid events.
- Manipulating a `.jsonl` trace file manually results in a `VERIFICATION_FAILED` status in `UI1`.

## confidence
high
