"""Write benchmark result artifacts locally and to the HF experiments bucket."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from huggingface_hub import HfFileSystem

DEFAULT_BUCKET_URI = "hf://buckets/SPerva/pillchecker-experiments"
_PREFIX_RE = re.compile(r"^benchmark-results/\d{4}-\d{2}-\d{2}/[^/]+/$")


def validate_output_prefix(output_prefix: str) -> str:
    """Require immutable benchmark result run prefixes."""
    if not _PREFIX_RE.match(output_prefix):
        raise ValueError(
            "output_prefix must look like benchmark-results/<YYYY-MM-DD>/<run-id>/"
        )
    return output_prefix


def write_run_artifacts(
    *,
    output_dir: str | Path,
    results: dict,
    manifest: dict,
    summary_markdown: str | None = None,
) -> dict[str, Path]:
    """Write the standard artifact set for one benchmark run."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    artifacts = {
        "results": output_path / "results.json",
        "manifest": output_path / "manifest.json",
    }
    _write_json(artifacts["results"], results)
    _write_json(artifacts["manifest"], manifest)

    if summary_markdown is not None:
        artifacts["summary"] = output_path / "summary.md"
        artifacts["summary"].write_text(summary_markdown, encoding="utf-8")

    return artifacts


def upload_run_artifacts(
    *,
    artifacts: dict[str, Path],
    output_prefix: str,
    bucket_uri: str = DEFAULT_BUCKET_URI,
    filesystem=None,
) -> list[str]:
    """Upload artifacts to the experiments bucket without overwriting prior runs."""
    validate_output_prefix(output_prefix)
    token = os.environ.get("HF_TOKEN")
    if filesystem is None and not token:
        raise RuntimeError("HF_TOKEN is required to upload benchmark artifacts")
    fs = filesystem or HfFileSystem(token=token)
    remote_paths: list[str] = []

    for name in ("results", "manifest", "predictions", "errors", "summary"):
        local_path = artifacts.get(name)
        if local_path is None:
            continue
        remote_path = f"{bucket_uri.rstrip('/')}/{output_prefix}{Path(local_path).name}"
        if fs.exists(remote_path):
            raise FileExistsError(f"Refusing to overwrite existing benchmark artifact: {remote_path}")
        with open(local_path, "rb") as source, fs.open(remote_path, "wb") as target:
            shutil.copyfileobj(source, target)
        remote_paths.append(remote_path)

    return remote_paths


def _write_json(path: Path, value: dict) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
