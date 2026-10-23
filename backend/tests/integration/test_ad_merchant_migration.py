"""The new seller migration preserves existing paid and unresolved checkouts."""

import sqlite3

import pytest

import aicl.db as db_module
import aicl.control.budget as budget_module
import aicl.commerce.service as commerce_module
from aicl.control.price_table import load_version
from aicl.db import to_iso
from test_mock_commerce import approved_purchase, ready


def snapshot(db, original_columns=None):
    with db.reader() as conn:
        tables = [row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name != 'schema_migration' ORDER BY name")]
        rows = {}
        for table in tables:
            cursor = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')
            columns = (original_columns or {}).get(table, [column[0] for column in cursor.description])
            rows[table] = [tuple(row[column] for column in columns) for row in cursor]
        return rows


def test_ad_seller_migration_preserves_paid_pending_rows_and_append_only_receipts(build_env, monkeypatch, tmp_path):
    migrations = db_module.MIGRATIONS_DIR
    old = tmp_path / "old-migrations"
    old.mkdir()
    for source in migrations.glob("*.sql"):
        if source.name < "0015_mock_ad_merchant.sql":
            (old / source.name).write_text(source.read_text())
    with monkeypatch.context() as patch:
        patch.setattr(db_module, "MIGRATIONS_DIR", old)
        # Build genuinely historical rows with the historical schema's two read
        # operations. Runtime code intentionally requires the current schema.
        def historical_price(conn, now):
            row = conn.execute("SELECT version FROM price_table_version WHERE effective_from <= ? ORDER BY effective_from DESC LIMIT 1", (to_iso(now),)).fetchone()
            return load_version(conn, row[0]) if row else None
        def historical_balance(self, conn, instance_id):
            return conn.execute("SELECT COALESCE(SUM(delta_micro_usd),0) FROM mock_commerce_ledger WHERE instance_id=?", (instance_id,)).fetchone()[0]
        patch.setattr(budget_module, "effective_version", historical_price)
        patch.setattr(commerce_module, "effective_version", historical_price)
        patch.setattr(commerce_module.MockCommerceService, "_balance", historical_balance)
        env, service, auth, inst, _ = ready(build_env)
        _, _, pending_order = approved_purchase(service, auth, inst.id)
        service.checkout(auth, pending_order["id"], "pending")
    before = snapshot(env.db)
    with env.db.reader() as conn:
        # Later migrations may append columns. Compare every original column and
        # row, retaining their ordering and values. Only the explicitly specified
        # new empty execution journals and pinned provider price seeds are added.
        original_columns = {table: [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
                            for table in before}
        triggers = [tuple(row) for row in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")]
        assert conn.execute("SELECT count(*) FROM mock_commerce_receipt").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM mock_commerce_order WHERE state='pending'").fetchone()[0] == 1

    def assert_preserved():
        after = snapshot(env.db, original_columns)
        for table in ("workflow_inference_attempt", "render_dispatch", "render_dispatch_attempt", "render_compute_usage", "judge_demo_workspace",
                      "assistant_session", "assistant_turn", "assistant_message", "assistant_proposal", "assistant_tool_event", "assistant_inference_attempt", "owner_request", "browser_session", "browser_attempt_evidence", "browser_purchase_proposal"):
            assert after.pop(table) == []
        model = "gpt-6-sol-2026-10-22"
        render = "render-flex-bound-2026-10-22"
        seeded_versions = [r for r in after["price_table_version"] if r[0] == model]
        assert seeded_versions == [(model, "2026-10-22T00:00:00.000000Z", "70174e72a0b7c1484ca49339e5cae99d74ed3eb09d0bec9f121ef7ccc3aa08d2", "2026-10-22T00:00:00.000000Z")]
        seeded_rates = [r for r in after["price_rate"] if r[0] == model]
        assert set(seeded_rates) == {(model, "inference.input_tokens", 1, 2), (model, "inference.output_tokens", 1, 10), (model, "compute.minutes", 1, 0)}
        render_versions = [r for r in after["price_table_version"] if r[0] == render]
        assert render_versions == [(render, "2026-10-22T00:00:00.000000Z", "d7c1899322d588d54bfffefa42682230d77d78f2e2be72d44c13a9d83f36796c", "2026-10-22T00:00:00.000000Z")]
        render_rates = [r for r in after["price_rate"] if r[0] == render]
        assert set(render_rates) == {(render, "inference.input_tokens", 1, 0), (render, "inference.output_tokens", 1, 0), (render, "compute.minutes", 1, 6667)}
        for table in ("price_table_version", "price_rate"):
            after[table] = [r for r in after[table] if r[0] not in (model, render)]
        assert after == before
        with env.db.reader() as conn:
            assert [tuple(row) for row in conn.execute("SELECT version,explicit_only FROM price_table_version WHERE version IN (?,?) ORDER BY version", (model, render))] == [(model, 1), (render, 1)]

    env.db.migrate()
    assert_preserved()
    with env.db.reader() as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        after_triggers = [tuple(row) for row in conn.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name")]
        new_names = {"render_compute_no_update", "render_compute_no_delete", "browser_purchase_proposal_snapshot_immutable"}
        assert [row for row in after_triggers if row[0] not in new_names] == triggers
        assert {row[0] for row in after_triggers} - {row[0] for row in triggers} == new_names
        assert conn.execute("SELECT 1 FROM schema_migration WHERE version='0015_mock_ad_merchant'").fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with env.db.transaction() as conn:
            conn.execute("UPDATE mock_commerce_receipt SET amount_minor=amount_minor+1")
    for mutation in ("UPDATE render_compute_usage SET cost_micro_usd=0", "DELETE FROM render_compute_usage"):
        with pytest.raises(sqlite3.IntegrityError, match="compute usage is append-only"):
            with env.db.transaction() as conn:
                hold_id = conn.execute("SELECT id FROM budget_hold WHERE instance_id=? LIMIT 1", (inst.id,)).fetchone()[0]
                conn.execute("INSERT INTO render_dispatch(id,instance_id,scheduled_for,kind,config_json,state,hold_id,created_at) VALUES ('render-trigger-proof',?,'trigger-proof','schedule','{}','completed',?,?)",
                             (inst.id, hold_id, to_iso(env.clock.now())))
                conn.execute("INSERT INTO render_compute_usage(dispatch_id,instance_id,hold_id,elapsed_seconds,charged_minutes,cost_micro_usd,created_at) VALUES ('render-trigger-proof',?,?,1,1,6667,?)",
                             (inst.id, hold_id, to_iso(env.clock.now())))
                conn.execute(mutation)
    env.db.migrate()
    assert_preserved()
    # The existing approved pending order still settles under its original binding.
    assert service.checkout(auth, pending_order["id"], "complete")["state"] == "completed"
