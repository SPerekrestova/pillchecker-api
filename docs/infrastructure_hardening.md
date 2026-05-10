# PillChecker GCP pipeline audit and hardening recommendations

This note summarizes the current GitHub Actions -> Google Cloud Run pipeline and the remaining hardening work.

## Current deployment path

- Workflow: `.github/workflows/ci-tests.yml`.
- Authentication: GitHub Actions uses Workload Identity Federation when `WIF_PROVIDER`, `WIF_SERVICE_ACCOUNT`, and `GCP_PROJECT_ID` are configured.
- Image registry: `europe-west1-docker.pkg.dev/<GCP_PROJECT_ID>/pillchecker-repo/api`.
- Runtime target: Cloud Run service `pillchecker-api` in `europe-west1`.
- Runtime secrets: `API_KEY` and `HF_TOKEN` are mounted from Secret Manager.
- DrugBank DB source: Docker build arg `DRUGBANK_DB_REPO`; it must point to an explicit GitHub release repo that publishes a `drugbank.db` asset.
- DrugBank DB release auth: Docker builds pass `DRUGBANK_DB_TOKEN` when configured; unauthenticated release downloads are allowed only for explicitly configured public DB repos.

## 1. IAM permissions: principle of least privilege

The workflow now supports a separate runtime service account through `CLOUD_RUN_SERVICE_ACCOUNT`, falling back to `deploy-sa@<project>.iam.gserviceaccount.com` for compatibility.

### Recommendations

- **Separate service accounts**:
  - **Deployer SA**: used only by GitHub Actions. Permissions: `roles/run.admin`, `roles/artifactregistry.writer`, and `roles/iam.serviceAccountUser` restricted to the runtime SA.
  - **Runtime SA**: used only by Cloud Run. Permissions: `roles/logging.logWriter` and `roles/secretmanager.secretAccessor` restricted to the exact runtime secrets.
- **Restrict secret access**: grant access only to `API_KEY` and `HF_TOKEN` unless another runtime secret is intentionally added.
- **Avoid default service accounts**: do not run the service as the Default Compute Service Account.

## 2. Cloud Run reliability: health probes

The current workflow deploys a container that exposes `/health`, but it does not explicitly configure HTTP startup or liveness probes.

### Recommendations

- Add an HTTP startup probe to `/health` so Cloud Run waits for application readiness, not just an open port.
- Add an HTTP liveness probe to `/health` to restart unhealthy containers.
- Keep `/health/data` for dependency-level diagnostics; do not use it as a startup probe because model and data dependencies may make startup slower.

Example service-level probe configuration:

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

## 3. Observability: structured logging

Audit logs are currently generated as JSON strings in `stdout`.

### Recommendations

- Standardize structured logs across application and audit logs.
- Include a `severity` field in JSON log payloads so Cloud Logging maps levels correctly.
- Define audit-log retention and export policy if compliance requires retention beyond the default Cloud Logging period.

## 4. Container security and dependency posture

Completed improvements:

- Runtime uses the non-root `pillchecker` user in `Dockerfile`.
- DrugBank interactions use direct SQLite integration instead of a Node.js MCP child process.
- The production image bakes the pinned DrugBank SQLite database at build time.

Remaining recommendations:

- Keep `DRUGBANK_DB_TAG` pinned for reproducibility.
- Configure `DRUGBANK_DB_REPO` to a maintained release source instead of relying on an upstream default.
- Configure `DRUGBANK_DB_TOKEN` if the DB release asset is private or rate-limited.
- Rebuild images when the pinned DrugBank release changes.
- Continue avoiding runtime downloads for required models and databases.

## 5. GitHub Actions -> GCP improvement plan

Execute this later as a staged hardening pass:

1. **Create a controlled DrugBank DB release source**: publish the reviewed `drugbank.db` as a private GitHub release asset or Artifact Registry object controlled by this project, then set `DRUGBANK_DB_REPO`, `DRUGBANK_DB_TAG`, and `DRUGBANK_DB_TOKEN` in GitHub Actions.
2. **Add a preflight job**: before Docker build, query the configured release, verify the expected asset name, record its size/checksum, and fail with a clear message if it is missing.
3. **Pin and verify the DB artifact**: add a required checksum secret or repository variable such as `DRUGBANK_DB_SHA256`; have `scripts/download_drugbank_db.py` or the Docker build verify it after download.
4. **Split build and deploy gates**: run local integration tests whenever a DB artifact is configured, but deploy to Cloud Run only after unit tests, image build, integration smoke tests, GCP auth, and DB checksum verification pass.
5. **Harden Cloud Run deployment flags**: add HTTP startup/liveness probes, explicit runtime service account, minimum/maximum instance policy, and revision labels containing Git SHA, DB tag, and dataset/model versions.
6. **Add post-deploy smoke tests**: after deployment, call `/health`, `/health/data`, and one authenticated `/interactions` smoke request against the Cloud Run URL; roll back or fail the workflow if they do not pass.
7. **Improve observability**: add structured severity fields, log the DB tag/checksum at startup, and create Cloud Logging alerts for startup failures, DrugBank connection failures, and repeated 5xx responses.

## 6. Network security

- If the API is only intended for a trusted frontend or mobile app, consider restricting ingress to `Internal and Cloud Load Balancing` and placing Cloud Armor in front of it.
- If outbound access should be restricted, use controlled egress through a VPC connector/NAT and allow only required external APIs such as NLM/RxNorm and Hugging Face.
