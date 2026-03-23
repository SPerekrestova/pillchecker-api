"""Tests for audit logging middleware."""

from app.middleware.audit_log import AuditContext, get_audit_context, init_audit_context


class TestAuditContext:
    def test_init_creates_context(self):
        ctx = init_audit_context()
        assert isinstance(ctx, AuditContext)
        assert ctx.entries == []

    def test_append_entry(self):
        ctx = init_audit_context()
        ctx.add("ner", {"entities": ["ibuprofen"]})
        assert len(ctx.entries) == 1
        assert ctx.entries[0]["stage"] == "ner"

    def test_get_returns_current_context(self):
        ctx = init_audit_context()
        ctx.add("test", {"data": "value"})
        retrieved = get_audit_context()
        assert retrieved is ctx

    def test_to_dict(self):
        ctx = init_audit_context()
        ctx.add("ner", {"count": 2})
        result = ctx.to_dict()
        assert "entries" in result
        assert "timestamp" in result
