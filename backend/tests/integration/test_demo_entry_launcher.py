"""Local entry defaults to a stable private link without SMTP or service startup."""

from contextlib import contextmanager
import stat
from types import SimpleNamespace

import pytest

from aicl import demo_server
from aicl.settings import SettingsError


def test_private_entry_files_are_stable_owner_only_and_settings_need_no_smtp(tmp_path):
    database = tmp_path / "local.db"
    token, url_file = demo_server.private_entry_files(database, 4173)
    token_file = database.with_name("local.db.private-access-token")
    assert token_file.read_text() == token + "\n"
    assert url_file.read_text() == f"http://127.0.0.1:4173/auth/access?token={token}\n"
    assert stat.S_IMODE(token_file.stat().st_mode) == stat.S_IMODE(url_file.stat().st_mode) == 0o600
    repeated, repeated_url_file = demo_server.private_entry_files(database, 4187)
    assert repeated == token and repeated_url_file == url_file
    assert url_file.read_text() == f"http://127.0.0.1:4187/auth/access?token={token}\n"
    settings = demo_server.demo_settings(database, 4187, local_private_entry=True, access_link_token=token)
    assert settings.private_entry_enabled and settings.local_private_entry
    assert not settings.smtp_host and not settings.smtp_from and settings.payment_mode == "mock"
    assert not demo_server.demo_settings(database, 4187).private_entry_enabled


@pytest.mark.parametrize("entry", [None, "email"])
def test_launcher_default_private_entry_logs_only_path_and_email_is_explicit(tmp_path, monkeypatch, capsys, entry):
    database = tmp_path / "local.db"
    calls = {}

    @contextmanager
    def payments(path, port):
        yield SimpleNamespace(url=f"http://127.0.0.1:{port}", token="test-payment-token-" + "x" * 32, database=path)

    def application(settings):
        calls["settings"] = settings
        return object()

    monkeypatch.setattr(demo_server, "local_payment_process", payments)
    monkeypatch.setattr(demo_server, "create_app", application)
    monkeypatch.setattr(demo_server.uvicorn, "run", lambda app, **kwargs: calls.update(server=kwargs))
    arguments = ["demo_server", "--database", str(database)]
    if entry:
        arguments += ["--entry", entry]
    monkeypatch.setattr("sys.argv", arguments)
    demo_server.main()
    output = capsys.readouterr().out
    assert calls["settings"].local_private_entry is (entry is None)
    assert calls["server"]["access_log"] is (entry is not None)
    assert calls["settings"].agent_runtime_mode == "off"
    if entry is None:
        assert str(database.with_name("local.db.private-access-url")) in output
        assert calls["settings"].access_link_token.get_secret_value() not in output
        assert "/auth/access?token=" not in output and "last-magic-link" not in output
    else:
        assert "last-magic-link" in output
        assert not database.with_name("local.db.private-access-token").exists()


@pytest.mark.parametrize("invalid", ["malformed", "shared", "symlink"])
def test_private_entry_rejects_unsafe_saved_token_without_echoing_contents(tmp_path, invalid):
    database = tmp_path / "local.db"
    token_file = database.with_name("local.db.private-access-token")
    content = "private but malformed entry credential" if invalid == "malformed" else "a" * 43
    target = tmp_path / "target" if invalid == "symlink" else token_file
    target.write_text(content)
    target.chmod(0o644 if invalid == "shared" else 0o600)
    if invalid == "symlink":
        token_file.symlink_to(target)
    with pytest.raises(SettingsError) as caught:
        demo_server.private_entry_files(database, 4173)
    assert content not in str(caught.value)
    assert target.read_text() == content
    assert not database.with_name("local.db.private-access-url").exists()
