#!/usr/bin/env python3
"""Sync the deployable GitHub tree to a Hugging Face Space."""

import argparse
import os
from pathlib import Path

from huggingface_hub import HfApi


DEFAULT_ALLOW_PATTERNS = [
    ".dockerignore",
    ".python-version",
    ".zenodo.json",
    "AGENTS.md",
    "CITATION.cff",
    "Dockerfile",
    "LICENSE",
    "README.md",
    "pyproject.toml",
    "uv.lock",
    "docker-compose.yml",
    "docker-compose.ci.yml",
    "app/**",
    "docs/**",
    "scripts/**",
    "tests/**",
]

DEFAULT_IGNORE_PATTERNS = [
    ".git/**",
    ".github/**",
    "eval/**",
    ".venv/**",
    "venv/**",
    "models/**",
    "data/**",
    "__pycache__/**",
    "*.pyc",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-id", default="SPerva/pillchecker-staging")
    parser.add_argument("--repo-type", default="space", choices=["space", "model", "dataset"])
    parser.add_argument("--revision", default="main")
    parser.add_argument("--path", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--commit-message", default=None)
    parser.add_argument("--no-prune", action="store_true")
    args = parser.parse_args()

    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN is required")

    root = Path(args.path).resolve()
    if not (root / "pyproject.toml").exists():
        raise SystemExit(f"{root} does not look like the repository root")

    api = HfApi(token=token)
    commit_message = (
        args.commit_message
        or f"Sync Space from GitHub {os.environ.get('GITHUB_SHA', '')}".strip()
    )

    api.upload_folder(
        repo_id=args.repo_id,
        repo_type=args.repo_type,
        revision=args.revision,
        folder_path=str(root),
        path_in_repo=".",
        allow_patterns=DEFAULT_ALLOW_PATTERNS,
        ignore_patterns=DEFAULT_IGNORE_PATTERNS,
        delete_patterns=None if args.no_prune else DEFAULT_ALLOW_PATTERNS,
        commit_message=commit_message,
    )


if __name__ == "__main__":
    main()
