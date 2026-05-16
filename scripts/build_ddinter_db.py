#!/usr/bin/env python3
"""Build a DDInter SQLite artefact for PillChecker.

Subcommands:
    fetch          download DDInter CSVs and write data/ddinter_manifest.json
    resolve-rxnorm build the RxNorm -> DDInter crosswalk (incremental)
    build          assemble data/ddinter.db from CSVs + crosswalk
    sanity-check   validate row counts, sentinel pair, size band

Run from the repository root: `python -m scripts.build_ddinter_db <cmd> ...`.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import datetime as _dt
import hashlib
import json
import logging
import sqlite3
import sys
import time
import urllib.parse
from collections.abc import Sequence
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from scripts import ddinter_sources

logger = logging.getLogger("build_ddinter_db")

USER_AGENT = "pillchecker-ddinter-build"

_REQUIRED_CSV_COLUMNS = {"DDInterID_A", "Drug_A", "DDInterID_B", "Drug_B", "Level"}


def compute_csv_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def compute_manifest_sha(files: dict[str, str]) -> str:
    """Deterministic hash over the sorted (filename, sha256) pairs."""
    sha = hashlib.sha256()
    for name in sorted(files):
        sha.update(name.encode("utf-8"))
        sha.update(b"\x00")
        sha.update(files[name].encode("ascii"))
        sha.update(b"\x00")
    return sha.hexdigest()


def write_fetch_manifest(path: Path, files: dict[str, str]) -> str:
    manifest_sha = compute_manifest_sha(files)
    payload = {
        "csv_sha256": files,
        "manifest_sha256": manifest_sha,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))
    return manifest_sha


def _download(url: str, dest: Path, timeout: float = 120.0) -> None:
    """Download url to dest atomically (write to .tmp, rename on success)."""
    req = Request(url, headers={"User-Agent": USER_AGENT})
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".tmp")
    try:
        with urlopen(req, timeout=timeout) as resp, tmp.open("wb") as out:
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(dest)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def cmd_fetch(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    files: dict[str, str] = {}
    for name in ddinter_sources.CSV_FILENAMES:
        url = ddinter_sources.csv_url(name)
        dest = out_dir / name
        logger.info("Fetching %s -> %s", url, dest)
        try:
            _download(url, dest)
        except (HTTPError, URLError) as exc:
            logger.error("Download failed for %s: %s", url, exc)
            return 2
        files[name] = compute_csv_sha256(dest)
    manifest_path = out_dir / "ddinter_manifest.json"
    write_fetch_manifest(manifest_path, files)
    logger.info("Wrote %s", manifest_path)
    return 0


def _validate_csv_headers(fieldnames: Sequence[str] | None, filename: str) -> None:
    """Raise ValueError if required columns are absent."""
    present = set(fieldnames or [])
    missing = _REQUIRED_CSV_COLUMNS - present
    if missing:
        raise ValueError(f"{filename}: missing columns {sorted(missing)!r}; got {sorted(present)!r}")


def collect_unique_drug_names(csv_dir: Path) -> dict[str, str]:
    """Walk every DDInter CSV in csv_dir and return {ddinter_id: name}.

    If a single id appears with multiple name spellings across files, the
    first spelling encountered wins (deterministic over sorted filenames).
    Opens with utf-8-sig to strip any BOM.
    """
    seen: dict[str, str] = {}
    for filename in sorted(ddinter_sources.CSV_FILENAMES):
        path = csv_dir / filename
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            _validate_csv_headers(reader.fieldnames, filename)
            for row in reader:
                for id_col, name_col in (("DDInterID_A", "Drug_A"), ("DDInterID_B", "Drug_B")):
                    did = (row.get(id_col) or "").strip()
                    name = (row.get(name_col) or "").strip()
                    if did and name and did not in seen:
                        seen[did] = name
    return seen


def reuse_crosswalk(
    previous: list[dict],
    current: dict[str, str],
) -> tuple[list[dict], dict[str, str]]:
    """Split current into (reused_rows, names_needing_resolution).

    A row is reused only when the previous release's ddinter_id matches AND
    the source_name string is byte-identical to the current name.
    """
    by_id: dict[str, dict] = {row["ddinter_id"]: row for row in previous}
    reused: list[dict] = []
    todo: dict[str, str] = {}
    for did, name in current.items():
        prior = by_id.get(did)
        if prior and prior.get("source_name") == name:
            reused.append(prior)
        else:
            todo[did] = name
    return reused, todo


_RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"


def _rxnorm_get(path: str, params: dict[str, str], timeout: float = 10.0, *, max_retries: int = 3) -> dict:
    """GET from RxNorm REST API with 429/Retry-After handling."""
    query = urllib.parse.urlencode(params)
    url = f"{_RXNORM_BASE}{path}?{query}"
    req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    for attempt in range(max_retries):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except HTTPError as exc:
            if exc.code == 429 and attempt < max_retries - 1:
                retry_after = float(exc.headers.get("Retry-After") or 60)
                logger.warning("RxNorm 429; sleeping %.0fs (Retry-After)", retry_after)
                time.sleep(retry_after)
            else:
                raise
    raise RuntimeError("unreachable")  # noqa: EM101


def resolve_via_rxnorm(
    name: str,
    *,
    per_request_delay: float = 0.0,
) -> tuple[str | None, str | None, str] | None:
    """Resolve a drug name via RxNorm.

    Sleeps per_request_delay before each HTTP call so the caller can enforce
    a per-request ceiling (not per-name, since up to 2 calls are made).

    Returns (rxcui, canonical_name, match_method) or None.
    """
    if per_request_delay:
        time.sleep(per_request_delay)
    exact = _rxnorm_get("/rxcui.json", {"name": name, "search": "2"})
    rxcui_list = exact.get("idGroup", {}).get("rxnormId") or []
    if rxcui_list:
        return rxcui_list[0], name, "exact"

    if per_request_delay:
        time.sleep(per_request_delay)
    approx = _rxnorm_get("/approximateTerm.json", {"term": name, "maxEntries": "1"})
    candidates = approx.get("approximateGroup", {}).get("candidate", [])
    if candidates:
        c = candidates[0]
        score = float(c.get("score") or 0)
        if score >= 80.0 and c.get("rxcui"):
            return c["rxcui"], c.get("name") or name, "approximate"
    return None


def _load_overrides(overrides_path: Path) -> dict[str, dict[str, str]]:
    """Manual rxcui overrides from a JSON file (gitignored by convention)."""
    if not overrides_path.exists():
        return {}
    return json.loads(overrides_path.read_text())


def cmd_resolve_rxnorm(args: argparse.Namespace) -> int:
    csv_dir = Path(args.csv_dir)
    out_path = Path(args.out_path)
    unmapped_out = Path(args.unmapped_out)
    prev_path = Path(args.previous) if args.previous else None

    current_names = collect_unique_drug_names(csv_dir)
    prev_rows: list[dict] = []
    if prev_path and prev_path.exists():
        prev_rows = json.loads(prev_path.read_text())
    reused, todo = reuse_crosswalk(prev_rows, current_names)
    logger.info("Crosswalk reuse: %d reused, %d to resolve", len(reused), len(todo))

    overrides = _load_overrides(Path(args.overrides))
    rows: list[dict] = list(reused)
    per_request_delay = 1.0 / max(args.rate_per_second, 1)
    unmapped_names: list[dict[str, str]] = []

    for did, name in sorted(todo.items()):
        if did in overrides:
            o = overrides[did]
            rows.append({
                "rxcui": o["rxcui"],
                "ddinter_id": did,
                "canonical_name": o.get("canonical_name", name),
                "match_method": "manual",
                "source_name": name,
            })
            continue
        try:
            resolved = resolve_via_rxnorm(name, per_request_delay=per_request_delay)
        except (HTTPError, URLError) as exc:
            logger.warning("RxNorm failed for %s (%s): %s", name, did, exc)
            resolved = None
        if resolved is None:
            logger.info("Unmapped: %s (%s)", name, did)
            unmapped_names.append({"ddinter_id": did, "name": name})
            continue
        rxcui, canonical, method = resolved
        rows.append({
            "rxcui": rxcui,
            "ddinter_id": did,
            "canonical_name": canonical,
            "match_method": method,
            "source_name": name,
        })

    unmapped_count = len(unmapped_names)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2, sort_keys=True))
    unmapped_out.parent.mkdir(parents=True, exist_ok=True)
    unmapped_out.write_text(json.dumps({"unmapped_count": unmapped_count, "names": unmapped_names}, indent=2))
    logger.info(
        "Wrote %s (%d mapped, %d unmapped)",
        out_path, len(rows), unmapped_count,
    )
    return 0


_SCHEMA_SQL = """
CREATE TABLE interactions (
    drug_a_id    TEXT NOT NULL,
    drug_a_name  TEXT NOT NULL,
    drug_b_id    TEXT NOT NULL,
    drug_b_name  TEXT NOT NULL,
    severity     TEXT NOT NULL CHECK (severity IN ('Minor','Moderate','Major')),
    atc_category TEXT NOT NULL,
    PRIMARY KEY (drug_a_id, drug_b_id)
);
CREATE INDEX idx_drug_a ON interactions(drug_a_id);
CREATE INDEX idx_drug_b ON interactions(drug_b_id);

CREATE TABLE rxnorm_to_ddinter (
    rxcui          TEXT PRIMARY KEY,
    ddinter_id     TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    match_method   TEXT NOT NULL CHECK (match_method IN ('exact','approximate','manual'))
);
CREATE INDEX idx_ddinter_id ON rxnorm_to_ddinter(ddinter_id);

CREATE VIRTUAL TABLE drug_names_fts USING fts5(
    ddinter_id UNINDEXED,
    name,
    tokenize='porter unicode61'
);

CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _iter_interaction_rows(csv_dir: Path):
    """Yield canonical (a_id, a_name, b_id, b_name, severity, category) tuples.

    Deduplicates pairs across CSVs: first-encountered severity wins.
    Warns when the same pair appears with a conflicting severity in a later CSV.
    Opens CSVs with utf-8-sig to strip BOM.
    """
    # key=(min_id, max_id) -> (a_id, a_name, b_id, b_name, severity, category, source_file)
    seen: dict[tuple[str, str], tuple] = {}
    for filename in sorted(ddinter_sources.CSV_FILENAMES):
        path = csv_dir / filename
        if not path.exists():
            continue
        category = ddinter_sources.atc_category(filename)
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            _validate_csv_headers(reader.fieldnames, filename)
            for row in reader:
                a_id = (row.get("DDInterID_A") or "").strip()
                a_name = (row.get("Drug_A") or "").strip()
                b_id = (row.get("DDInterID_B") or "").strip()
                b_name = (row.get("Drug_B") or "").strip()
                severity = (row.get("Level") or "").strip()
                if not (a_id and b_id and severity):
                    continue
                # Canonical ordering so (A,B) and (B,A) map to the same key.
                if a_id > b_id:
                    a_id, a_name, b_id, b_name = b_id, b_name, a_id, a_name
                key = (a_id, b_id)
                if key in seen:
                    prev = seen[key]
                    if prev[4] != severity:
                        logger.warning(
                            "Severity conflict for %s+%s: keeping %s (from %s), ignoring %s (from %s)",
                            a_id, b_id, prev[4], prev[6], severity, filename,
                        )
                else:
                    seen[key] = (a_id, a_name, b_id, b_name, severity, category, filename)

    for row in seen.values():
        yield row[:6]  # strip the internal source_file field


def _dedupe_crosswalk_rows(crosswalk: list[dict]) -> list[dict]:
    """Return crosswalk rows with at most one DDInter mapping per RxCUI.

    RxNorm can resolve brand/synonym DDInter names to the same concept. The
    SQLite schema keys by RxCUI, so keep the first deterministic row from the
    JSON input and warn about later aliases.
    """
    by_rxcui: dict[str, dict] = {}
    for row in crosswalk:
        rxcui = row["rxcui"]
        if rxcui in by_rxcui:
            kept = by_rxcui[rxcui]
            logger.warning(
                "Duplicate RxCUI %s: keeping %s (%s), ignoring %s (%s)",
                rxcui,
                kept["ddinter_id"],
                kept["source_name"],
                row["ddinter_id"],
                row["source_name"],
            )
            continue
        by_rxcui[rxcui] = row
    return list(by_rxcui.values())


def cmd_build(args: argparse.Namespace) -> int:
    csv_dir = Path(args.csv_dir)
    crosswalk = _dedupe_crosswalk_rows(json.loads(Path(args.crosswalk).read_text()))
    manifest = json.loads(Path(args.manifest).read_text())
    out = Path(args.out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    with contextlib.closing(sqlite3.connect(out)) as conn:
        conn.executescript(_SCHEMA_SQL)

        conn.executemany(
            "INSERT OR IGNORE INTO interactions VALUES (?, ?, ?, ?, ?, ?)",
            list(_iter_interaction_rows(csv_dir)),
        )

        conn.executemany(
            "INSERT INTO rxnorm_to_ddinter (rxcui, ddinter_id, canonical_name, match_method) VALUES (?, ?, ?, ?)",
            [(r["rxcui"], r["ddinter_id"], r["canonical_name"], r["match_method"]) for r in crosswalk],
        )

        # FTS5: deduped union of interaction names + crosswalk canonical names
        name_seen: set[tuple[str, str]] = set()
        for did, name in conn.execute("SELECT drug_a_id, drug_a_name FROM interactions"):
            key = (did, name.lower())
            if key not in name_seen:
                name_seen.add(key)
                conn.execute("INSERT INTO drug_names_fts (ddinter_id, name) VALUES (?, ?)", (did, name))
        for did, name in conn.execute("SELECT drug_b_id, drug_b_name FROM interactions"):
            key = (did, name.lower())
            if key not in name_seen:
                name_seen.add(key)
                conn.execute("INSERT INTO drug_names_fts (ddinter_id, name) VALUES (?, ?)", (did, name))
        for row in crosswalk:
            key = (row["ddinter_id"], row["canonical_name"].lower())
            if key not in name_seen:
                name_seen.add(key)
                conn.execute(
                    "INSERT INTO drug_names_fts (ddinter_id, name) VALUES (?, ?)",
                    (row["ddinter_id"], row["canonical_name"]),
                )

        row_counts = {
            "interactions": conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
            "rxnorm_crosswalk_exact": conn.execute(
                "SELECT COUNT(*) FROM rxnorm_to_ddinter WHERE match_method='exact'"
            ).fetchone()[0],
            "rxnorm_crosswalk_approximate": conn.execute(
                "SELECT COUNT(*) FROM rxnorm_to_ddinter WHERE match_method='approximate'"
            ).fetchone()[0],
            "rxnorm_crosswalk_manual": conn.execute(
                "SELECT COUNT(*) FROM rxnorm_to_ddinter WHERE match_method='manual'"
            ).fetchone()[0],
        }

        now = _dt.datetime.now(_dt.timezone.utc).isoformat()
        meta_rows: dict[str, str] = {
            "source_release": args.tag,
            "build_timestamp": now,
            "csv_sha256_manifest": manifest.get("manifest_sha256", ""),
            "ddinter_url": ddinter_sources.DDINTER_BASE_URL,
            "row_count_interactions": str(row_counts["interactions"]),
            "row_count_crosswalk_exact": str(row_counts["rxnorm_crosswalk_exact"]),
            "row_count_crosswalk_approximate": str(row_counts["rxnorm_crosswalk_approximate"]),
            "row_count_crosswalk_manual": str(row_counts["rxnorm_crosswalk_manual"]),
            "rxnorm_rest_fetched_at": now,
        }
        build_sha = getattr(args, "build_sha", "") or ""
        if build_sha:
            meta_rows["build_sha"] = build_sha
        conn.executemany(
            "INSERT INTO meta (key, value) VALUES (?, ?)",
            list(meta_rows.items()),
        )
        conn.commit()

    logger.info("Wrote %s (interactions=%d)", out, row_counts["interactions"])
    return 0


def sanity_check(
    db_path: Path,
    *,
    min_rows: int = 250_000,
    sentinel: tuple[str, str] = ("Warfarin", "Aspirin"),
    expected_severity: str = "Major",
    previous_size_bytes: int | None,
    size_drift_tolerance: float = 0.20,
) -> bool:
    with contextlib.closing(sqlite3.connect(db_path)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0]
        if rows < min_rows:
            logger.error("Sanity: rows %d < min %d", rows, min_rows)
            return False
        a, b = sentinel
        row = conn.execute(
            """
            SELECT severity FROM interactions
            WHERE (LOWER(drug_a_name)=LOWER(?) AND LOWER(drug_b_name)=LOWER(?))
               OR (LOWER(drug_a_name)=LOWER(?) AND LOWER(drug_b_name)=LOWER(?))
            LIMIT 1
            """,
            (a, b, b, a),
        ).fetchone()
        if row is None:
            logger.error("Sanity: sentinel %s+%s not found", a, b)
            return False
        if row["severity"] != expected_severity:
            logger.error("Sanity: sentinel severity %s != %s", row["severity"], expected_severity)
            return False
    if previous_size_bytes is not None:
        actual = db_path.stat().st_size
        drift = abs(actual - previous_size_bytes) / max(previous_size_bytes, 1)
        if drift > size_drift_tolerance:
            logger.error("Sanity: size drift %.2f%% > %.0f%%", drift * 100, size_drift_tolerance * 100)
            return False
    return True


def cmd_sanity_check(args: argparse.Namespace) -> int:
    ok = sanity_check(
        Path(args.db_path),
        min_rows=args.min_rows,
        sentinel=tuple(args.sentinel),
        expected_severity=args.expected_severity,
        previous_size_bytes=args.previous_size_bytes,
    )
    return 0 if ok else 1


def write_release_manifest(
    out_path: Path,
    *,
    tag: str,
    csv_sha256: dict[str, str],
    manifest_sha256: str,
    db_sha256: str,
    db_size: int,
    row_counts: dict[str, int],
    rxnorm_crosswalk_unmapped: int = 0,
    rxnorm_fetched_at: str,
    build_sha: str = "",
) -> None:
    # Attribution: Zhang Y, et al. DDInter 2.0 (2023). Verify citation before first release.
    payload = {
        "tag": tag,
        "ddinter_source": ddinter_sources.DDINTER_BASE_URL,
        "ddinter_version": "2.0",
        "csv_sha256": csv_sha256,
        "manifest_sha256": manifest_sha256,
        "db_sha256": db_sha256,
        "db_size_bytes": db_size,
        "row_counts": {**row_counts, "rxnorm_crosswalk_unmapped": rxnorm_crosswalk_unmapped},
        "license": "CC BY-NC-SA 4.0",
        "attribution": "Zhang Y, et al. DDInter 2.0: an updated comprehensive database for drug-drug interactions. (CC BY-NC-SA 4.0)",
        "rxnorm_rest_fetched_at": rxnorm_fetched_at,
    }
    if build_sha:
        payload["build_sha"] = build_sha
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_fetch = sub.add_parser("fetch", help="Download CSVs + write manifest")
    p_fetch.add_argument("--out-dir", default="data", help="Output directory")
    p_fetch.set_defaults(func=cmd_fetch)

    p_rx = sub.add_parser("resolve-rxnorm", help="Build the RxNorm crosswalk")
    p_rx.add_argument("--csv-dir", default="data")
    p_rx.add_argument("--out-path", default="data/ddinter_crosswalk.json")
    p_rx.add_argument("--unmapped-out", default="data/ddinter_unmapped.json",
                      help="Sidecar JSON listing unmapped drug names")
    p_rx.add_argument("--previous", default=None, help="Path to previous release crosswalk JSON")
    p_rx.add_argument("--overrides", default="data/rxnorm_overrides.json",
                      help="Path to manual rxcui overrides JSON (need not exist)")
    p_rx.add_argument("--rate-per-second", type=int, default=15,
                      help="Max RxNorm HTTP requests per second (each drug name uses up to 2 calls)")
    p_rx.set_defaults(func=cmd_resolve_rxnorm)

    p_build = sub.add_parser("build", help="Emit ddinter.db from CSVs + crosswalk")
    p_build.add_argument("--csv-dir", default="data")
    p_build.add_argument("--crosswalk", default="data/ddinter_crosswalk.json")
    p_build.add_argument("--manifest", default="data/ddinter_manifest.json")
    p_build.add_argument("--out-path", default="data/ddinter.db")
    p_build.add_argument("--tag", required=True, help="Release tag (e.g. ddinter-2026-05-15)")
    p_build.add_argument("--build-sha", default="", help="Git commit SHA for provenance (optional)")
    p_build.set_defaults(func=cmd_build)

    p_check = sub.add_parser("sanity-check", help="Validate emitted SQLite")
    p_check.add_argument("--db-path", required=True)
    p_check.add_argument("--min-rows", type=int, default=250_000)
    p_check.add_argument("--sentinel", nargs=2, default=["Warfarin", "Aspirin"])
    p_check.add_argument("--expected-severity", default="Major")
    p_check.add_argument("--previous-size-bytes", type=int, default=None)
    p_check.set_defaults(func=cmd_sanity_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = _build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
