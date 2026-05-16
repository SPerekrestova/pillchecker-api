#!/usr/bin/env python3
"""Download the pinned DDInter SQLite release asset from a GitHub release."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

USER_AGENT = "pillchecker-api-build"
DEFAULT_ASSET = "ddinter.db"


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _request(url: str, token: str | None, accept: str) -> Request:
    headers = {
        "Accept": accept,
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return Request(url, headers=headers)


def _download_request(url: str) -> Request:
    return Request(url, headers={"User-Agent": USER_AGENT})


def _load_release(repo: str, tag: str, token: str | None) -> dict[str, object]:
    url = f"https://api.github.com/repos/{repo}/releases/tags/{tag}"
    with urlopen(_request(url, token, "application/vnd.github+json"), timeout=60) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise RuntimeError(f"GitHub release response for {repo}@{tag} was not an object")
    return data


def _find_asset_url(release: dict[str, object], asset_name: str) -> str:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise RuntimeError("GitHub release response did not include an assets list")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        if asset.get("name") == asset_name and isinstance(asset.get("url"), str):
            return str(asset["url"])
    available = [str(asset.get("name")) for asset in assets if isinstance(asset, dict)]
    raise RuntimeError(f"Asset {asset_name!r} not found. Available assets: {available}")


def _copy_response(response, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "wb") as handle:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            handle.write(chunk)


def _download_asset(asset_url: str, output: Path, token: str | None) -> None:
    opener = build_opener(_NoRedirectHandler)
    try:
        with opener.open(_request(asset_url, token, "application/octet-stream"), timeout=120) as response:
            _copy_response(response, output)
            return
    except HTTPError as exc:
        if exc.code not in {301, 302, 303, 307, 308}:
            raise
        location = exc.headers.get("Location")
        if not location:
            raise RuntimeError("GitHub release asset redirect did not include a Location header") from exc

    with urlopen(_download_request(location), timeout=120) as response:
        _copy_response(response, output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--asset", default=DEFAULT_ASSET)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    # Public release; token is optional and only raises GitHub API limits.
    token = os.environ.get("GITHUB_TOKEN")
    try:
        release = _load_release(args.repo, args.tag, token)
        asset_url = _find_asset_url(release, args.asset)
        _download_asset(asset_url, Path(args.output), token)
    except HTTPError as exc:
        raise SystemExit(
            f"Failed to download {args.asset} from {args.repo}@{args.tag}: HTTP {exc.code}"
        ) from exc


if __name__ == "__main__":
    main()
