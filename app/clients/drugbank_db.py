"""Direct SQLite client for DrugBank database.

Provides async access to the pre-built DrugBank SQLite database,
replacing the Node.js MCP server child process.
"""

import asyncio
import json
import logging
import os
import aiosqlite
from typing import Any

logger = logging.getLogger(__name__)

# Default path relative to app root
DEFAULT_DB_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "drugbank-mcp-server", "data", "drugbank.db"
)
DB_PATH = os.environ.get("DRUGBANK_DB_PATH", DEFAULT_DB_PATH)


def _escape_fts5_query(query: str) -> str:
    """Escape a user-supplied string for use as an FTS5 MATCH phrase.

    FTS5 assigns special meaning to characters like `*`, `"`, `(`, `)`,
    `:`, `-`, `^`, and keywords (AND, OR, NOT, NEAR). Wrapping the term in
    double quotes turns it into a phrase where most operators are treated
    literally; internal quotes must be doubled to escape them.
    """
    return '"' + query.replace('"', '""') + '"'


class DrugBankDatabase:
    """Async handler for DrugBank SQLite database."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> None:
        """Establish connection to the database."""
        if self._conn is not None:
            return

        async with self._connect_lock:
            if self._conn is not None:
                return

            if not os.path.exists(self.db_path):
                logger.error("DrugBank database not found at %s", self.db_path)
                raise FileNotFoundError(f"DrugBank database not found: {self.db_path}")

            conn = await aiosqlite.connect(self.db_path)
            conn.row_factory = aiosqlite.Row
            # Enable WAL mode for better concurrency
            await conn.execute("PRAGMA journal_mode = WAL")
            self._conn = conn
            logger.info("Connected to DrugBank SQLite database at %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def health_check(self) -> bool:
        """Verify the database connection is actually usable.

        Runs a lightweight `SELECT 1` to ensure the underlying file is still
        readable and the connection has not been broken. If the probe fails
        the cached connection is discarded so the next query can re-establish
        it rather than reusing a dead handle.
        """
        try:
            if self._conn is None:
                await self.connect()
            assert self._conn is not None
            async with self._conn.execute("SELECT 1") as cursor:
                await cursor.fetchone()
            return True
        except Exception as exc:
            logger.warning("DrugBank health check failed: %s", exc)
            # Drop the broken handle so subsequent calls reconnect.
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:
                    pass
                self._conn = None
            return False

    async def search_by_name(self, query: str, limit: int = 1) -> list[dict[str, Any]]:
        """Search for drugs by name using FTS5 index.

        Returns list of drug summaries (matching MCP search_by_name). An
        empty list means the query ran successfully but no rows matched.
        Operational errors (e.g. missing database, corrupt file) propagate
        to the caller so transient failures are not conflated with "not
        found" and cached as such.
        """
        if not self._conn:
            await self.connect()
        assert self._conn is not None

        sql = """
            SELECT drugs.* FROM drugs_fts
            JOIN drugs ON drugs_fts.drugbank_id = drugs.drugbank_id
            WHERE drugs_fts.name MATCH ?
            LIMIT ?
        """
        escaped = _escape_fts5_query(query)
        async with self._conn.execute(sql, (escaped, limit)) as cursor:
            rows = await cursor.fetchall()
            return [self._format_summary(dict(row)) for row in rows]

    async def get_drug_interactions(self, drugbank_id: str) -> list[dict[str, Any]]:
        """Get interactions for a drug by its DrugBank ID.

        Returns list of interaction dicts. An empty list means the drug has
        no recorded interactions (or the drug row is missing); operational
        errors propagate to the caller.
        """
        if not self._conn:
            await self.connect()
        assert self._conn is not None

        sql = "SELECT drug_interactions FROM drugs WHERE drugbank_id = ?"
        async with self._conn.execute(sql, (drugbank_id,)) as cursor:
            row = await cursor.fetchone()
            if not row:
                return []

            raw_interactions = row["drug_interactions"]
            if not raw_interactions:
                return []

            try:
                interactions = json.loads(raw_interactions)
            except (json.JSONDecodeError, TypeError) as exc:
                logger.warning(
                    "Malformed drug_interactions JSON for %s: %s", drugbank_id, exc
                )
                return []
            return [
                {
                    "name": entry.get("name"),
                    "description": entry.get("description"),
                    "severity": entry.get("severity"),
                }
                for entry in interactions
            ]

    def _format_summary(self, row: dict[str, Any]) -> dict[str, Any]:
        """Format a database row into a summary dict matching the MCP tool output."""
        return {
            "drugbank_id": row.get("drugbank_id"),
            "name": row.get("name"),
            "description": row.get("description"),
            "groups": self._safe_json_parse(row.get("groups")),
            "cas_number": row.get("cas_number"),
            "state": row.get("state"),
        }

    @staticmethod
    def _safe_json_parse(data: Any) -> Any:
        if not data:
            return []
        if isinstance(data, (list, dict)):
            return data
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return []


# Singleton instance
db = DrugBankDatabase()
