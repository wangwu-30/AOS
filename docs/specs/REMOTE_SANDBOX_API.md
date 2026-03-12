# Remote Sandbox API Specification

## Overview

This document defines the HTTP/JSON API contract for the `RemoteExecutor` to communicate with a compliant Sandbox Service. This API allows the AgentOS Kernel to offload skill execution to a secure, isolated environment (e.g., Cloud Sandbox, Firecracker microVM cluster).

## Design Principles

-   **Schema-First**: Defined via OpenAPI (Swagger) compatible structure.
-   **Async-First**: Execution is long-running; API favors polling or webhooks (MVP: Polling).
-   **Stateless**: Each execution request is self-contained.
-   **Secure**: Authentication via Bearer tokens; payload encryption (future).

## Base URL

`https://<sandbox-endpoint>/v1`

## Authentication

All requests MUST include:
`Authorization: Bearer <sk_sandbox_...>`

## Resources

### 1. Execute Skill

Submit a skill execution job.

-   **Endpoint**: `POST /execute`
-   **Content-Type**: `application/json`

#### Request Body

```json
{
  "workspace_id": "string",
  "operator_ref": "string (s3://... or registry://... or presigned_url)",
  "arguments": { ... },
  "idempotency_key": "string (uuid)",
  "deadline_ms": 60000,
  "trace_context": {
    "trace_id": "string",
    "turn_id": "string",
    "span_id": "string"
  },
  "policy_context": {
    "model": "string (optional, model routing key)",
    "memory_context": {
      "schema_version": "2.0.0",
      "l0_continuity": {
        "workspace_id": "string",
        "conversation_id": "string|null",
        "active_project_id": "string|null"
      },
      "l1_query": {
        "query": "string",
        "intent": "identity|preference|continuity|procedure|delivery|generic",
        "limit": 5
      },
      "l2_hits": [
        {
          "record_id": "mr_...",
          "kind": "profile|preference|procedure|anti_pattern|delivery_summary|note|turn_archive",
          "summary": "string",
          "evidence_ref": "ev_..."
        }
      ],
      "conflicts": [],
      "retrieval_ref": "ev_..."
    },
    "allow_network_egress": false,
    "verify_asvp": true
  }
}
```

> **Constraint**: The `policy_context` object is an extension point. Servers **MAY** ignore unknown keys but **SHOULD** log them for forward compatibility. Clients **MAY** send additional policy keys (e.g., `executor_preference`, `cost_budget`) here without breaking the contract.

> **Note on `memory_context`**: In MVP, `memory_context` is carried via `policy_context` as a forward-compatible extension point (Spike-MEMCTX1). If future kernel-level governance requires enforcing size/depth/quota without parsing arbitrary policy blobs, this may be promoted to a top-level field in a versioned request.

> **Note on `operator_ref`**: In MVP, this might assume the sandbox has access to the skill/operator via a shared storage or registry. For the initial spike, we may support a direct `zip_url` or similar.

#### Response (202 Accepted)

```json
{
  "execution_id": "exec_123456789",
  "status": "pending",
  "status_url": "/v1/executions/exec_123456789"
}
```

#### Error Responses
-   400 Bad Request: Invalid input schema.
-   401 Unauthorized: Invalid API key.
-   429 Too Many Requests: Rate limit exceeded.

---

### 2. Get Execution Status

Poll for the result of an execution.

-   **Endpoint**: `GET /executions/{execution_id}`

#### Response (200 OK)

```json
{
  "execution_id": "exec_123456789",
  "status": "pending | running | completed | failed | timeout",
  "created_at": "2026-02-17T12:00:00Z",
  "updated_at": "2026-02-17T12:00:05Z",
  "result": {
    "ok": true,
    "output": { ... },
    "error_code": null,
    "evidence_refs": [ ... ],
    "usage": {
      "latency_ms": 1500,
      "tokens": 100
    }
  }
}
```

> The `result` field is null until `status` is terminal (`completed`, `failed`, `timeout`).

## Data Types

### ExecutionStatus

Enum: `["pending", "running", "completed", "failed", "timeout", "canceled"]`

### ErrorCode

Standard AgentOS error codes (e.g., `E_TIMEOUT`, `E_EXECUTION_FAILED`, `E_HITL_REQUIRED`).

## Future Considerations

-   **Streaming**: Server-Sent Events (SSE) for real-time logs/trace updates.
-   **Artifacts**: Mechanism to upload/download artifacts generated during execution.
-   **Webhooks**: Callback URL to avoid polling.
