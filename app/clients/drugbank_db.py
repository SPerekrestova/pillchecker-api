"""Direct SQLite client for DrugBank database.

Provides async access to the pre-built DrugBank SQLite database,
replacing the Node.js MCP server child process.
"""

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


class DrugBankDatabase:
    """Async handler for DrugBank SQLite database."""

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Establish connection to the database."""
        if self._conn is not None:
            return

        if not os.path.exists(self.db_path):
            logger.error("DrugBank database not found at %s", self.db_path)
            raise FileNotFoundError(f"DrugBank database not found: {self.db_path}")

        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        # Enable WAL mode for better concurrency
        await self._conn.execute("PRAGMA journal_mode = WAL")
        logger.info("Connected to DrugBank SQLite database at %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def search_by_name(self, query: str, limit: int = 1) -> list[dict[str, Any]]:
        """Search for drugs by name using FTS5 index.

        Returns list of drug summaries (matching MCP search_by_name).
        """
        if not self._conn:
            await self.connect()

        # Mirroring drugbank-parser-sqlite.js:
        # SELECT drugs.* FROM drugs_fts
        # JOIN drugs ON drugs_fts.drugbank_id = drugs.drugbank_id
        # WHERE drugs_fts.name MATCH ?
        # LIMIT ?
        sql = """
            SELECT drugs.* FROM drugs_fts
            JOIN drugs ON drugs_fts.drugbank_id = drugs.drugbank_id
            WHERE drugs_fts.name MATCH ?
            LIMIT ?
        """
        try:
            async with self._conn.execute(sql, (query, limit)) as cursor:
                rows = await cursor.fetchall()
                return [self._format_summary(dict(row)) for row in rows]
        except Exception as e:
            logger.error("Search by name failed for '%s': %s", query, e)
            return []

    async def get_drug_interactions(self, drugbank_id: str) -> list[dict[str, Any]]:
        """Get interactions for a drug by its DrugBank ID.

        Returns list of interaction dicts.
        """
        if not self._conn:
            await self.connect()

        sql = "SELECT drug_interactions FROM drugs WHERE drugbank_id = ?"
        try:
            async with self._conn.execute(sql, (drugbank_id,)) as cursor:
                row = await cursor.fetchone()
                if not row:
                    return []
                
                raw_interactions = row["drug_interactions"]
                if not raw_interactions:
                    return []
                
                interactions = json.loads(raw_interactions)
                # Map to format expected by drugbank_client.py
                return [
                    {
                        "name": entry.get("name"),
                        "description": entry.get("description"),
                        "severity": entry.get("severity"),
                    }
                    for entry in interactions
                ]
        except Exception as e:
            logger.error("Failed to fetch interactions for %s: %s", drugbank_id, e)
            return []

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
