from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_tier1_benchmark_workflow_contract():
    workflow = (ROOT / ".github/workflows/tier1-benchmark.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch:" in workflow
    for input_name in ("dataset_revision", "limit", "run_id", "concurrency", "upload"):
        assert f"{input_name}:" in workflow

    assert "concurrency:" in workflow
    assert "group: tier1-benchmark" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "dataset_revision must not contain commas" in workflow
    assert "BENCHMARK_JOB: pillchecker-benchmark-tier1" in workflow
    assert 'gcloud run jobs deploy "${{ env.BENCHMARK_JOB }}"' in workflow
    assert 'gcloud run jobs execute "${{ env.BENCHMARK_JOB }}"' in workflow
    assert "--task-timeout=60m" in workflow
    assert "HF_TOKEN=HF_TOKEN:latest" in workflow
    assert "INTERACTION_DB_REPO" in workflow
    assert "INTERACTION_DB_TAG" in workflow
    assert "INTERACTION_DB_SHA256" in workflow
    assert 'tr -d "\\r\\n"' in workflow
    assert 'INTERACTION_DB_REPO="$(printf' in workflow
    assert 'INTERACTION_DB_TAG="$(printf' in workflow
    assert "--record-timeout-seconds" in workflow
    assert "hf://buckets/SPerva/pillchecker-experiments" in workflow
    assert 'bucket = os.environ["BENCHMARK_BUCKET"]' in workflow
    assert "0 < sample_size <= expected_limit" in workflow
    assert "len(predictions) == sample_size" in workflow

    for artifact in ("manifest.json", "results.json", "predictions.jsonl", "errors.jsonl", "summary.md"):
        assert artifact in workflow


def test_dockerfile_has_separate_runtime_and_benchmark_targets():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    ci_workflow = (ROOT / ".github/workflows/ci-tests.yml").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim AS app-base" in dockerfile
    assert "FROM app-base AS benchmark-runner" in dockerfile
    assert "FROM app-base AS runtime" in dockerfile
    assert "COPY eval/ /app/eval/" in dockerfile
    assert 'ENTRYPOINT ["python", "-m", "eval.run_benchmark"]' in dockerfile
    assert 'INTERACTION_DB_REPO="$(printf' in dockerfile
    assert 'INTERACTION_DB_TAG="$(printf' in dockerfile
    assert 'tr -d "\\r\\n"' in dockerfile

    assert "target: runtime" in ci_workflow
    assert "--target runtime" in ci_workflow
