"""Mock payment transport must stay local and never disclose its shared token."""

import pytest

from aicl.settings import Settings, SettingsError


def test_mock_payment_settings_default_inline_and_accept_explicit_local_api(base_env):
    assert Settings.from_env(base_env).payment_api_url == ""
    token = "private-payment-fixture-token"
    configured = Settings.from_env({**base_env, "AICL_MOCK_PAYMENT_API_URL": "http://127.0.0.1:4174",
                                   "AICL_MOCK_PAYMENT_TOKEN": token})
    assert configured.payment_api_url == "http://127.0.0.1:4174"
    assert configured.payment_token.get_secret_value() == token
    assert token not in repr(configured) and token not in configured.model_dump_json()


def test_mock_payment_settings_reject_remote_ambiguous_and_production_transport(base_env):
    for url in ("https://127.0.0.1:4174", "http://localhost:4174", "http://example.test:4174",
                "http://127.0.0.1", "http://127.0.0.1:0", "http://127.0.0.1:65536",
                "http://127.0.0.1:4174/", "http://127.0.0.1:4174/path",
                "http://127.0.0.1:4174?token=secret", "http://127.0.0.1:4174#x",
                "http://secret@127.0.0.1:4174", "http://127.0.0.1:4174\n"):
        with pytest.raises(SettingsError) as caught:
            Settings.from_env({**base_env, "AICL_MOCK_PAYMENT_API_URL": url,
                               "AICL_MOCK_PAYMENT_TOKEN": "do-not-print-me"})
        assert "secret@" not in str(caught.value) and "token=secret" not in str(caught.value)
        assert "do-not-print-me" not in str(caught.value)
    for overrides in ({"AICL_MOCK_PAYMENT_TOKEN": ""},
                      {"AICL_ENVIRONMENT": "production", "AICL_PUBLIC_BASE_URL": "https://habitat.example"}):
        with pytest.raises(SettingsError):
            Settings.from_env({**base_env, "AICL_MOCK_PAYMENT_API_URL": "http://127.0.0.1:4174",
                               "AICL_MOCK_PAYMENT_TOKEN": "local-token", **overrides})
    with pytest.raises(SettingsError):
        Settings.from_env({**base_env, "AICL_ENVIRONMENT": "production",
                           "AICL_PUBLIC_BASE_URL": "https://habitat.example",
                           "AICL_MOCK_PAYMENT_TOKEN": "local-token"})


def test_mock_payment_launcher_owns_process_and_keeps_credentials_private(tmp_path):
    import socket
    import stat

    from aicl.commerce.local_payment_process import local_payment_process

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        with pytest.raises(RuntimeError, match="already in use"):
            with local_payment_process(tmp_path / "provider.db", port):
                pytest.fail("must not adopt an existing listener")
    with pytest.raises(ValueError, match="caller failure"):
        with local_payment_process(tmp_path / "provider.db", port) as provider:
            token = provider.token
            assert token not in repr(provider)
            assert provider.database.is_file()
            token_file = tmp_path / ".mock-payment-token"
            assert stat.S_IMODE(token_file.stat().st_mode) == 0o600
            raise ValueError("caller failure")
    # Exceptional application exit still stops only the child and frees its port.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))
    with local_payment_process(tmp_path / "provider.db", port) as restarted:
        assert restarted.token == token
