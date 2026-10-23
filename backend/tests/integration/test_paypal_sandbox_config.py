"""Sandbox selection is explicit, isolated, secret-safe and validates before networking."""

from types import SimpleNamespace

import pytest

from aicl.commerce.factory import commerce_service
from aicl.sandbox_server import build_sandbox_settings, main, read_credentials_file
from aicl.settings import Settings, SettingsError

SERVICE = {
    "AICL_PAYMENT_MODE": "paypal_sandbox",
    "AICL_PAYPAL_CLIENT_ID": "service-client-id",
    "AICL_PAYPAL_CLIENT_SECRET": "service-private-secret",
    "AICL_PAYPAL_MERCHANT_ID": "SERVICE123",
}
PURCHASE = {
    "AICL_PAYPAL_PURCHASE_CLIENT_ID": "purchase-client-id",
    "AICL_PAYPAL_PURCHASE_CLIENT_SECRET": "purchase-private-secret",
    "AICL_PAYPAL_PURCHASE_MERCHANT_ID": "PURCHASE123",
}


def test_explicit_adapter_selection_and_secret_redaction(base_env):
    assert Settings.from_env(base_env).payment_mode == "mock"
    settings = Settings.from_env({**base_env, **SERVICE, **PURCHASE})
    for secret in (SERVICE["AICL_PAYPAL_CLIENT_SECRET"], PURCHASE["AICL_PAYPAL_PURCHASE_CLIENT_SECRET"]):
        assert secret not in repr(settings)
        assert secret not in settings.model_dump_json()
    service = commerce_service(SimpleNamespace(settings=settings, db=object(), clock=object()))
    assert service.payments.transport == "paypal_sandbox"
    assert service.payments.supports_purchases is True
    funding_only = Settings.from_env({**base_env, **SERVICE})
    service = commerce_service(SimpleNamespace(settings=funding_only, db=object(), clock=object()))
    assert service.payments.supports_purchases is False


@pytest.mark.parametrize("change,variable", [
    ({"AICL_PAYMENT_MODE": "live"}, "AICL_PAYMENT_MODE"),
    ({"AICL_PAYMENT_MODE": "paypal_live"}, "AICL_PAYMENT_MODE"),
    ({"AICL_PAYMENT_MODE": "mock"}, "AICL_PAYMENT_MODE"),
    ({"AICL_ENVIRONMENT": "production", "AICL_PUBLIC_BASE_URL": "https://habitat.example"}, "AICL_PAYMENT_MODE"),
    ({"AICL_PAYPAL_CLIENT_ID": ""}, "AICL_PAYPAL_CLIENT_ID"),
    ({"AICL_PAYPAL_CLIENT_SECRET": ""}, "AICL_PAYPAL_CLIENT_SECRET"),
    ({"AICL_PAYPAL_MERCHANT_ID": ""}, "AICL_PAYPAL_MERCHANT_ID"),
    ({"AICL_PAYPAL_MERCHANT_ID": "buyer@example.test"}, "AICL_PAYPAL_MERCHANT_ID"),
    ({"AICL_PAYPAL_CLIENT_SECRET": "secret with spaces"}, "AICL_PAYPAL_CLIENT_SECRET"),
    ({"AICL_PAYPAL_CLIENT_SECRET": "CHANGE_ME_SECRET"}, "AICL_PAYPAL_CLIENT_SECRET"),
    ({"AICL_PAYPAL_PURCHASE_CLIENT_ID": "purchase-only"}, "AICL_PAYPAL_PURCHASE_CLIENT_SECRET"),
    ({"AICL_PAYPAL_PURCHASE_CLIENT_SECRET": "purchase-only"}, "AICL_PAYPAL_PURCHASE_CLIENT_ID"),
    ({"AICL_MOCK_PAYMENT_TOKEN": "mixed-mock-token-abcdefghijkl"}, "AICL_PAYMENT_MODE"),
    ({"AICL_MOCK_PAYMENT_API_URL": "http://127.0.0.1:4174", "AICL_MOCK_PAYMENT_TOKEN": "mixed-mock-token-abcdefghijkl"}, "AICL_PAYMENT_MODE"),
])
def test_invalid_sandbox_settings_name_variables_never_values(base_env, change, variable):
    with pytest.raises(SettingsError) as caught:
        Settings.from_env({**base_env, **SERVICE, **change})
    assert caught.value.variable == variable
    assert SERVICE["AICL_PAYPAL_CLIENT_SECRET"] not in str(caught.value)
    assert "secret with spaces" not in str(caught.value)
    assert "mixed-mock-token-abcdefghijkl" not in str(caught.value)


@pytest.mark.parametrize("url", [
    "http://example.test", "https://secret@example.test", "https://example.test/path",
    "https://example.test?next=https://evil.example", "https://example.test#fragment",
    "https://example.test?", "https://example.test#", "https://example.test:65536",
    "https://example.test:bad", "https://example.test\\@evil.example", "https://example.test\n",
    "//example.test", "javascript:alert(1)",
])
def test_return_origin_cannot_smuggle_redirects_or_credentials(base_env, url):
    with pytest.raises(SettingsError, match="AICL_PUBLIC_BASE_URL"):
        Settings.from_env({**base_env, **SERVICE, "AICL_PUBLIC_BASE_URL": url})


def test_direct_settings_and_unvalidated_copy_cannot_bypass_payment_guards(base_env):
    valid = Settings.from_env(base_env)
    with pytest.raises(SettingsError, match="AICL_PAYPAL_CLIENT_ID"):
        Settings(**{**valid.model_dump(), "payment_mode": "paypal_sandbox"})
    unsafe = valid.model_copy(update={"payment_mode": "paypal_live"})
    with pytest.raises(SettingsError, match="AICL_PAYMENT_MODE"):
        commerce_service(SimpleNamespace(settings=unsafe))


def test_literal_credentials_file_and_isolated_settings(tmp_path):
    path = tmp_path / "sandbox.env"
    path.write_text("# Test fixtures only\n" + "\n".join(f'{name}="{value}"' for name, value in SERVICE.items()))
    values = read_credentials_file(path)
    assert values == SERVICE
    settings = build_sandbox_settings(tmp_path / "isolated.db", 4180, values)
    assert settings.environment == "test" and settings.test_mode
    assert settings.public_base_url == "http://127.0.0.1:4180"
    assert settings.database_url == f"sqlite:///{tmp_path / 'isolated.db'}"
    assert settings.payment_api_url == "" and settings.payment_mode == "paypal_sandbox"
    assert not (tmp_path / "isolated.db").exists()


@pytest.mark.parametrize("line", [
    "export AICL_PAYPAL_CLIENT_ID=bad", "OTHER_SECRET=do-not-print",
    "AICL_PAYPAL_CLIENT_SECRET=$(touch should-not-exist)",
    "AICL_PAYPAL_CLIENT_SECRET=`touch should-not-exist`",
    'AICL_PAYPAL_CLIENT_SECRET="unterminated',
    "AICL_PAYPAL_CLIENT_SECRET=value\nAICL_PAYPAL_CLIENT_SECRET=duplicate",
    "AICL_PAYPAL_CLIENT_SECRET=value\\nother",
])
def test_credentials_file_does_not_execute_or_disclose_invalid_lines(tmp_path, line):
    path = tmp_path / "sandbox.env"
    path.write_text(line)
    with pytest.raises(SettingsError) as caught:
        read_credentials_file(path)
    assert "do-not-print" not in str(caught.value)
    assert "should-not-exist" not in str(caught.value)
    assert not (tmp_path / "should-not-exist").exists()


def test_check_config_never_builds_app_or_contacts_paypal(tmp_path, monkeypatch, capsys):
    path = tmp_path / "sandbox.env"
    path.write_text("\n".join(f"{name}={value}" for name, value in SERVICE.items()))
    monkeypatch.setattr("sys.argv", ["sandbox_server", "--credentials-file", str(path), "--check-config"])
    monkeypatch.setattr("aicl.sandbox_server.create_app", lambda _: pytest.fail("must not build app"))
    monkeypatch.setattr("aicl.sandbox_server.uvicorn.run", lambda *_a, **_k: pytest.fail("must not listen"))
    main()
    output = capsys.readouterr().out
    assert "No API request or transaction" in output
    assert SERVICE["AICL_PAYPAL_CLIENT_SECRET"] not in output
