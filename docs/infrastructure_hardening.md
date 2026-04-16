# PillChecker Infrastructure Hardening Recommendations

Following an assessment of the current CI/CD and Google Cloud Platform (GCP) setup, the following improvements are recommended to enhance security, reliability, and observability.

## 1. IAM Permissions: Principle of Least Privilege

Currently, the `deploy-sa` service account is used for both CI/CD (deployment) and runtime (execution on Cloud Run). It also has project-wide access to all secrets.

### Recommendations:

*   **Separate Service Accounts**: Split `deploy-sa` into two distinct roles:
    *   **Deployer SA**: Used only by GitHub Actions. Permissions: `roles/run.admin`, `roles/artifactregistry.writer`, `roles/iam.serviceAccountUser` (restricted to the Runner SA).
    *   **Runner SA**: Used only by the Cloud Run service at runtime. Permissions: `roles/logging.logWriter`, `roles/secretmanager.secretAccessor` (restricted to specific secrets).
*   **Restrict Secret Access**: Instead of granting `roles/secretmanager.secretAccessor` at the project level, grant it only on the specific secrets the application needs (`API_KEY`, `HF_TOKEN`, `DRUGBANK_DB_REPO`).
*   **Remove Default Service Account**: Ensure the Default Compute Service Account is not used and has no permissions, as it often has broad `Editor` access by default.

## 2. Cloud Run Reliability: Health Probes

The current Cloud Run configuration uses a basic `tcpSocket` startup probe.

### Recommendations:

*   **Switch to HTTP Probes**: Use `httpGet` probes to `/health` instead of `tcpSocket`. This ensures the application is not just listening on a port but is actually ready to handle requests.
*   **Add Liveness Probe**: Implement a liveness probe to automatically restart the container if the Python process deadlocks or becomes unresponsive.
*   **Example Configuration**:
    ```yaml
    startupProbe:
      httpGet:
        path: /health
        port: 8000
      failureThreshold: 5
      periodSeconds: 10
    livenessProbe:
      httpGet:
        path: /health
        port: 8000
      periodSeconds: 30
    ```

## 3. Observability: Structured Logging

Audit logs are currently generated as JSON strings in `stdout`.

### Recommendations:

*   **Standardize Structured Logging**: Use a logging library (like `structlog` or `google-cloud-logging`) to ensure all logs, not just audit logs, are emitted as structured JSON.
*   **Cloud Logging Integration**: Ensure `severity` levels (INFO, WARNING, ERROR) are correctly mapped to GCP Cloud Logging levels by including a `"severity"` field in the JSON payload.
*   **Log Retention**: Ensure audit logs are retained for a period sufficient for compliance/auditing (e.g., 365 days), potentially exporting them to BigQuery for long-term analysis.

## 4. Container Optimization (Completed)

We have already improved the container security and efficiency by:
*   Switching to a **non-root user** (`pillchecker`) in the `Dockerfile`.
*   Replacing the Node.js-based MCP server with **direct SQLite integration**, which:
    *   Reduced the image size (no Node.js runtime or binaries).
    *   Eliminated child process management overhead and latency.
    *   Removed Node-specific security vulnerabilities from the attack surface.

## 5. Network Security

*   **Ingress Control**: If the API is only intended for use by a specific frontend or mobile app, consider restricting ingress to `Internal and Cloud Load Balancing` and placing a Cloud Armor policy in front of it.
*   **Egress Control**: If the application only needs to talk to specific external APIs (like NLM or HuggingFace), consider using a VPC Service Control or a NAT Gateway with restricted egress rules.
