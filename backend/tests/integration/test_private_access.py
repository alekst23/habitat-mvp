"""Private-link configuration, rotation and upgrade from public demo access."""

import hashlib
import hmac
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

import aicl.db as database_module
from aicl.auth.judge_demo import accept_access_link, valid_entry_token
from aicl.auth.magic_link import CaptureMagicLinkSender
from aicl.auth.session import SqliteSignInService
from aicl.db import Database, to_iso
from aicl.settings import Settings, SettingsError
from test_judge_demo import ACCESS_TOKEN, judge_env


def test_private_link_configuration_is_required_and_secret(base_env):
    config = judge_env(base_env)
    for value in ("", "short", "CHANGE_ME_" + "x" * 32, "x" * 31 + " ", "é" * 40,
                  base_env["AICL_SESSION_SECRET"]):
        with pytest.raises(SettingsError) as caught:
            Settings.from_env({**config, "AICL_ACCESS_LINK_TOKEN": value})
        assert caught.value.variable == "AICL_ACCESS_LINK_TOKEN"
    settings = Settings.from_env(config)
    assert ACCESS_TOKEN not in repr(settings)
    assert ACCESS_TOKEN not in settings.model_dump_json()
    # Revalidation also guards direct/unvalidated construction at app startup.
    with pytest.raises(SettingsError):
        Settings.model_validate({**settings.model_dump(), "access_link_token": SecretStr("")})


def test_rotating_private_link_invalidates_unused_proofs_and_legacy_public_tokens(build_env, base_env):
    env = build_env()
    ctx = SimpleNamespace(settings=Settings.from_env(judge_env(base_env)), clock=env.clock)
    proof = accept_access_link(ctx, ACCESS_TOKEN)
    assert proof and valid_entry_token(ctx, proof)
    assert ACCESS_TOKEN not in proof
    for invalid in ("", "wrong", "é" * 40, "x" * 129):
        assert accept_access_link(ctx, invalid) is None
    # The former public endpoint issued signed v1 proofs to anyone.
    payload = proof.rsplit(".", 1)[0]
    old_signature = hmac.new(ctx.settings.session_secret.encode(),
                             ("habitat-judge-entry-v1:" + payload).encode(), hashlib.sha256).hexdigest()
    assert not valid_entry_token(ctx, payload + "." + old_signature)
    rotated = "rotated-access-" + "r" * 32
    ctx.settings = Settings.model_validate({**ctx.settings.model_dump(), "access_link_token": SecretStr(rotated)})
    assert accept_access_link(ctx, ACCESS_TOKEN) is None
    assert not valid_entry_token(ctx, proof)
    fresh = accept_access_link(ctx, rotated)
    assert fresh and valid_entry_token(ctx, fresh)


def test_upgrade_expires_old_public_workspaces_and_sessions_without_erasing_owners(build_env, tmp_path, monkeypatch):
    env = build_env()
    legacy = tmp_path / "legacy-migrations"
    legacy.mkdir()
    for source in database_module.MIGRATIONS_DIR.glob("*.sql"):
        if source.name < "0021_private_access.sql":
            (legacy / source.name).write_text(source.read_text())
    db = Database(f"sqlite:///{tmp_path / 'legacy.db'}")
    with monkeypatch.context() as patch:
        patch.setattr(database_module, "MIGRATIONS_DIR", legacy)
        db.migrate()
    now, expires = to_iso(env.clock.now()), to_iso(env.clock.now() + timedelta(days=1))
    with db.transaction() as conn:
        for name in ("demo", "named"):
            conn.execute("INSERT INTO owner(id,email_hash,created_at) VALUES (?,?,?)", (name, name, now))
            conn.execute("INSERT INTO session(id_hash,owner_id,created_at,expires_at) VALUES (?,?,?,?)",
                         (hashlib.sha256(name.encode()).hexdigest(), name, now, expires))
        conn.execute("INSERT INTO judge_demo_workspace(owner_id,entry_nonce_hash,created_at,expires_at) "
                     "VALUES ('demo','nonce',?,?)", (now, expires))
    service = SqliteSignInService(db, env.clock, env.audit, CaptureMagicLinkSender(),
                                 identity_key="i" * 40, public_base_url="https://habitat.example")
    assert service.resolve_session("demo") is not None
    db.migrate()
    assert service.resolve_session("demo") is None
    assert service.resolve_session("named") is not None
    with db.reader() as conn:
        assert conn.execute("SELECT expires_at FROM judge_demo_workspace").fetchone()[0] <= now
        assert conn.execute("SELECT count(*) FROM owner").fetchone()[0] == 2
        assert conn.execute("SELECT revoked_at FROM session WHERE owner_id='demo'").fetchone()[0] is not None
    # Restarting after a new private-link login must not expire its workspace again.
    with db.transaction() as conn:
        conn.execute("UPDATE judge_demo_workspace SET expires_at=?", (expires,))
    db.migrate()
    with db.reader() as conn:
        assert conn.execute("SELECT expires_at FROM judge_demo_workspace").fetchone()[0] == expires
