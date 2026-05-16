"""Async SQLite client for the DDInter interaction database."""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "ddinter.db")
DB_PATH = os.environ.get("INTERACTION_DB_PATH", DEFAULT_DB_PATH)


def _escape_fts5(query: str) -> str:
    """Wrap a user string as an FTS5 phrase, escaping internal quotes."""
    return '"' + query.replace('"', '""') + '"'


class DDInterDatabase:
    """Async handle for the DDInter SQLite database."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        if self._conn is not None:
            return
        async with self._connect_lock:
            if self._conn is not None:
                return
            if not os.path.exists(self.db_path):
                logger.error("DDInter database not found at %s", self.db_path)
                raise FileNotFoundError(f"DDInter database not found: {self.db_path}")
            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            await conn.execute("PRAGMA journal_mode = WAL")
            self._conn = conn
            logger.info("Connected to DDInter SQLite at %s", self.db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def health_check(self) -> bool:
        try:
            if self._conn is None:
                await self.connect()
            assert self._conn is not None
            async with self._conn.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except Exception as exc:
            logger.warning("DDInter health check failed: %s", exc)
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return False

    async def _ddinter_ids_for_rxcuis(self, rxcuis: list[str]) -> dict[str, str]:
        if not rxcuis:
            return {}
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        placeholders = ",".join("?" * len(rxcuis))
        async with self._conn.execute(
            f"SELECT rxcui, ddinter_id FROM rxnorm_to_ddinter WHERE rxcui IN ({placeholders})",
            tuple(rxcuis),
        ) as cursor:
            rows = await cursor.fetchall()
        return {row["rxcui"]: row["ddinter_id"] for row in rows}

    async def _lookup_pair(self, ddinter_a: str, ddinter_b: str) -> dict[str, Any] | None:
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        async with self._conn.execute(
            """
            SELECT drug_a_id, drug_a_name, drug_b_id, drug_b_name, severity, atc_category
            FROM interactions
            WHERE (drug_a_id = ? AND drug_b_id = ?)
               OR (drug_a_id = ? AND drug_b_id = ?)
            LIMIT 1
            """,
            (ddinter_a, ddinter_b, ddinter_b, ddinter_a),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return {
            "drug_a_id": row["drug_a_id"],
            "drug_b_id": row["drug_b_id"],
            "drug_a_name": row["drug_a_name"],
            "drug_b_name": row["drug_b_name"],
            "severity": row["severity"].lower(),
            "atc_category": row["atc_category"],
            "source": "ddinter",
        }

    async def lookup_by_rxcui(self, rxcui_a: str, rxcui_b: str) -> dict[str, Any] | None:
        mapping = await self._ddinter_ids_for_rxcuis([rxcui_a, rxcui_b])
        ddinter_a = mapping.get(rxcui_a)
        ddinter_b = mapping.get(rxcui_b)
        if not ddinter_a or not ddinter_b:
            return None
        return await self._lookup_pair(ddinter_a, ddinter_b)

    async def _fts_ddinter_id_for_name(self, name: str) -> str | None:
        if self._conn is None:
            await self.connect()
        assert self._conn is not None
        async with self._conn.execute(
            "SELECT ddinter_id FROM drug_names_fts WHERE name MATCH ? LIMIT 1",
            (_escape_fts5(name),),
        ) as cursor:
            row = await cursor.fetchone()
        return row["ddinter_id"] if row else None

    async def lookup_by_name_fts(self, name_a: str, name_b: str) -> dict[str, Any] | None:
        try:
            ddinter_a = await self._fts_ddinter_id_for_name(name_a)
            ddinter_b = await self._fts_ddinter_id_for_name(name_b)
        except Exception as exc:
            logger.warning("DDInter FTS5 lookup failed: %s", exc)
            return None
        if not ddinter_a or not ddinter_b:
            return None
        return await self._lookup_pair(ddinter_a, ddinter_b)


client = DDInterDatabase()
