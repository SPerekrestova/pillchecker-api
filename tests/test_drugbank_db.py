"""Tests for the direct SQLite DrugBank client."""

import json
import os
import sqlite3
import tempfile

import pytest

from app.clients.drugbank_db import DrugBankDatabase, _escape_fts5_query


@pytest.fixture
def db_path():
    """Create a temporary SQLite DB that mirrors the drugbank schema."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE drugs (
                drugbank_id TEXT PRIMARY KEY,
                name TEXT,
                description TEXT,
                groups TEXT,
                cas_number TEXT,
                state TEXT,
                drug_interactions TEXT
            );
            CREATE VIRTUAL TABLE drugs_fts USING fts5(drugbank_id UNINDEXED, name);
            """
        )
        conn.executemany(
            "INSERT INTO drugs (drugbank_id, name, description, groups, cas_number, state, drug_interactions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    "DB01050",
                    "Ibuprofen",
                    "NSAID",
                    json.dumps(["approved"]),
                    "15687-27-1",
                    "solid",
                    json.dumps(
                        [
                            {
                                "name": "Warfarin",
                                "description": "Increases bleeding risk.",
                                "severity": "major",
                            }
                        ]
                    ),
                ),
                (
                    "DB00682",
                    "Warfarin",
                    "Anticoagulant",
                    json.dumps(["approved"]),
                    "81-81-2",
                    "solid",
                    json.dumps(
                        [
                            {
                                "name": "Ibuprofen",
                                "description": "Bleeding.",
                                "severity": "major",
                            }
                        ]
                    ),
                ),
                (
                    "DB0NOINT",
                    "Lonelydrug",
                    "No interactions recorded",
                    None,
                    None,
                    None,
                    None,
                ),
            ],
        )
        conn.executemany(
            "INSERT INTO drugs_fts (drugbank_id, name) VALUES (?, ?)",
            [
                ("DB01050", "Ibuprofen"),
                ("DB00682", "Warfarin"),
                ("DB0NOINT", "Lonelydrug"),
            ],
        )
        conn.commit()
    finally:
        conn.close()

    yield path
    os.remove(path)


@pytest.fixture
async def db(db_path):
    instance = DrugBankDatabase(db_path=db_path)
    yield instance
    await instance.close()


class TestConnect:
    async def test_connect_missing_db_raises(self):
        instance = DrugBankDatabase(db_path="/nonexistent/path/drugbank.db")
        with pytest.raises(FileNotFoundError):
            await instance.connect()

    async def test_connect_is_idempotent(self, db):
        await db.connect()
        conn = db._conn
        await db.connect()
        # Same connection object -- no leak on repeated calls
        assert db._conn is conn


class TestSearchByName:
    async def test_finds_existing_drug(self, db):
        rows = await db.search_by_name("Ibuprofen")
        assert len(rows) == 1
        assert rows[0]["drugbank_id"] == "DB01050"

    async def test_returns_empty_for_unknown_drug(self, db):
        rows = await db.search_by_name("notarealdrug")
        assert rows == []

    async def test_handles_fts5_special_characters(self, db):
        """FTS5 has special syntax for `*`, `"`, `:`, `(`, etc.

        The client must escape these rather than passing them directly.
        """
        # Without escaping, a bare double-quote would be a parse error.
        rows = await db.search_by_name('"aspirin"')
        assert rows == []  # returns empty, not an exception

        # A hyphen is treated as NOT by default; escaping should leave it literal.
        rows = await db.search_by_name("anti-inflammatory")
        assert rows == []


class TestGetDrugInteractions:
    async def test_returns_interactions(self, db):
        rows = await db.get_drug_interactions("DB01050")
        assert len(rows) == 1
        assert rows[0]["name"] == "Warfarin"
        assert rows[0]["severity"] == "major"

    async def test_returns_empty_for_missing_drug(self, db):
        rows = await db.get_drug_interactions("DBNOPE999")
        assert rows == []

    async def test_returns_empty_when_drug_has_null_interactions(self, db):
        rows = await db.get_drug_interactions("DB0NOINT")
        assert rows == []


class TestHealthCheck:
    async def test_healthy(self, db):
        assert await db.health_check() is True

    async def test_unhealthy_when_db_missing(self):
        instance = DrugBankDatabase(db_path="/nonexistent/path/drugbank.db")
        assert await instance.health_check() is False

    async def test_unhealthy_when_underlying_connection_broken(self, db):
        await db.connect()
        # Simulate the connection being closed under us; subsequent queries fail.
        await db._conn.close()
        assert await db.health_check() is False

    async def test_failed_health_check_resets_connection(self, db):
        """A broken connection must be dropped so the next call can reconnect."""
        await db.connect()
        await db._conn.close()
        assert await db.health_check() is False
        # _conn should be reset so subsequent queries re-establish it.
        assert db._conn is None
        # After reset the next query reconnects and succeeds.
        rows = await db.search_by_name("Ibuprofen")
        assert len(rows) == 1


class TestFTS5Escape:
    def test_wraps_in_quotes(self):
        assert _escape_fts5_query("aspirin") == '"aspirin"'

    def test_escapes_internal_quotes(self):
        assert _escape_fts5_query('say "hi"') == '"say ""hi"""'

    def test_leaves_hyphens_alone_inside_phrase(self):
        assert _escape_fts5_query("anti-inflammatory") == '"anti-inflammatory"'
