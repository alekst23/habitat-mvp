"""Operator configuration cannot silently replace the disclosure recipient."""
import argparse

import pytest

from aicl.settings import Settings, SettingsError
from aicl.workflow.inference_config import add_inference_arguments, with_inference_settings


def arguments(*values):
    parser = argparse.ArgumentParser()
    add_inference_arguments(parser)
    return parser.parse_args(values)


def test_search_credentials_stay_secret_and_cli_preserves_operator_binding(base_env):
    env = {**base_env, "BRAVE_SEARCH_API_KEY": "fixture-brave-secret-123",
           "AICL_RESEARCH_PROVIDER_ACCOUNT": "approved-account",
           "AICL_RESEARCH_CREDENTIAL_BINDING": "key-version-1",
           "AICL_RESEARCH_WORKER_IMAGE": "sha256:" + "a" * 64}
    settings = Settings.from_env(env)
    result = with_inference_settings(settings, arguments())
    assert result.brave_search_api_key.get_secret_value() == "fixture-brave-secret-123"
    assert result.research_provider_account == "approved-account"
    assert result.research_worker_image == "sha256:" + "a" * 64
    assert "fixture-brave-secret-123" not in result.model_dump_json()
    assert "fixture-brave-secret-123" not in repr(result)


@pytest.mark.parametrize("content", ["BRAVE_SEARCH_API_KEY=$(cat secret)",
    "BRAVE_SEARCH_API_KEY=`cat secret`", "BRAVE_SEARCH_API_KEY=abc\nBRAVE_SEARCH_API_KEY=def",
    "BRAVE_SEARCH_API_KEY=key\nCOMMAND=run", "BRAVE_SEARCH_API_KEY='private-key'"])
def test_search_key_file_is_never_executed_or_loosely_parsed(base_env, tmp_path, content):
    path = tmp_path / "credentials"
    path.write_text(content)
    path.chmod(0o600)
    with pytest.raises(SettingsError) as error:
        with_inference_settings(Settings.from_env(base_env), arguments("--search-key-file", str(path)))
    assert content not in str(error.value)


def test_search_key_requires_private_permissions_and_explicit_recipient(base_env, tmp_path):
    path = tmp_path / "credentials"
    path.write_text("BRAVE_SEARCH_API_KEY=fixture-brave-private-key")
    path.chmod(0o644)
    with pytest.raises(SettingsError, match="readable only"):
        with_inference_settings(Settings.from_env(base_env), arguments("--search-key-file", str(path)))
    path.chmod(0o600)
    with pytest.raises(SettingsError, match="AICL_RESEARCH_PROVIDER_ACCOUNT"):
        with_inference_settings(Settings.from_env(base_env), arguments("--search-key-file", str(path)))
    configured = with_inference_settings(Settings.from_env(base_env), arguments("--search-key-file", str(path),
        "--search-account", "brave-account", "--search-credential-binding", "key-v1"))
    assert configured.brave_search_api_key.get_secret_value() == "fixture-brave-private-key"


def test_mutable_worker_image_is_rejected(base_env):
    with pytest.raises(SettingsError, match="immutable"):
        Settings.from_env({**base_env, "AICL_RESEARCH_WORKER_IMAGE": "python:latest"})
