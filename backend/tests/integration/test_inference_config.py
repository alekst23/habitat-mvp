"""Real inference is an explicit, bounded, secret-safe local-demo choice."""

import pytest
from types import SimpleNamespace

from aicl.settings import Settings, SettingsError
from aicl.workflow.inference_config import read_openai_key_file, with_inference_settings, inference_startup_message
from aicl.workflow.factory import workflow_service


def test_live_inference_configuration_is_explicit_and_secret_safe(base_env):
    default = Settings.from_env(base_env)
    assert default.inference_mode == "mock"
    settings = Settings.from_env({**base_env, "AICL_INFERENCE_MODE": "openai", "OPENAI_API_KEY": "test-private-openai-key"})
    assert settings.inference_mode == "openai"
    assert settings.inference_max_spend_micro_usd == 1_000_000
    assert settings.openai_api_key.get_secret_value() == "test-private-openai-key"
    assert "test-private-openai-key" not in repr(settings)
    assert "test-private-openai-key" not in settings.model_dump_json()


@pytest.mark.parametrize("change,variable", [
    ({"AICL_INFERENCE_MODE": "other"}, "AICL_INFERENCE_MODE"),
    ({"AICL_INFERENCE_MODE": "openai"}, "OPENAI_API_KEY"),
    ({"AICL_INFERENCE_MODE": "openai", "OPENAI_API_KEY": "key with spaces"}, "OPENAI_API_KEY"),
    ({"AICL_INFERENCE_MODE": "openai", "OPENAI_API_KEY": "CHANGE_ME_KEY"}, "OPENAI_API_KEY"),
    ({"AICL_INFERENCE_MAX_SPEND_MICRO_USD": "0"}, "AICL_INFERENCE_MAX_SPEND_MICRO_USD"),
    ({"AICL_INFERENCE_MAX_SPEND_MICRO_USD": "10000001"}, "AICL_INFERENCE_MAX_SPEND_MICRO_USD"),
    ({"AICL_INFERENCE_MAX_SPEND_MICRO_USD": "1.5"}, "AICL_INFERENCE_MAX_SPEND_MICRO_USD"),
    ({"AICL_INFERENCE_MODE": "openai", "OPENAI_API_KEY": "test-private-openai-key", "AICL_ENVIRONMENT": "production", "AICL_PUBLIC_BASE_URL": "https://habitat.example"}, "AICL_INFERENCE_MODE"),
])
def test_invalid_inference_configuration_fails_closed_without_secret(base_env, change, variable):
    with pytest.raises(SettingsError) as caught:
        Settings.from_env({**base_env, **change})
    assert caught.value.variable == variable
    assert "test-private-openai-key" not in str(caught.value)
    assert "key with spaces" not in str(caught.value)


def test_direct_settings_constructor_also_validates(base_env):
    valid = Settings.from_env(base_env)
    with pytest.raises(SettingsError, match="OPENAI_API_KEY"):
        Settings.model_validate({**valid.model_dump(), "inference_mode": "openai"})


def test_factory_wires_only_explicit_live_mode_and_revalidates_copies(base_env):
    settings = Settings.from_env(base_env)
    ctx = SimpleNamespace(settings=settings, db=object(), clock=object())
    assert workflow_service(ctx).inference is None
    ctx.settings = Settings.from_env({**base_env, "AICL_INFERENCE_MODE": "openai", "OPENAI_API_KEY": "test-private-openai-key"})
    service = workflow_service(ctx)
    assert service.inference.cap == 1_000_000
    assert type(service.inference.adapter).__name__ == "OpenAIInferenceAdapter"
    ctx.settings = settings.model_copy(update={"inference_mode": "openai"})
    with pytest.raises(SettingsError, match="OPENAI_API_KEY"):
        workflow_service(ctx)


def test_literal_key_file_never_executes_or_loads_unrelated_settings(tmp_path, base_env):
    path = tmp_path / "credentials.env"
    sentinel = tmp_path / "must-not-exist"
    path.write_text(f"UNRELATED=$(touch {sentinel})\nexport OPENAI_API_KEY='test-private-openai-key'\n")
    assert read_openai_key_file(path) == "test-private-openai-key"
    assert not sentinel.exists()
    args = SimpleNamespace(inference="openai", inference_key_file=path, inference_max_spend_micro_usd=200_000)
    settings = with_inference_settings(Settings.from_env(base_env), args)
    assert settings.inference_max_spend_micro_usd == 200_000
    assert "GPT-6 Sol" in inference_startup_message(settings)
    assert "$0.20" in inference_startup_message(settings)
    assert "test-private-openai-key" not in inference_startup_message(settings)
    with pytest.raises(SettingsError, match="choose openai"):
        with_inference_settings(settings, SimpleNamespace(**{**vars(args), "inference": "mock"}))


@pytest.mark.parametrize("text", [
    "# no key", "OPENAI_API_KEY=test-key\nOPENAI_API_KEY=duplicate-key",
    "OPENAI_API_KEY=$(bad-command)", "OPENAI_API_KEY='unclosed", "OPENAI_API_KEY=`command`",
])
def test_invalid_key_files_never_echo_contents(tmp_path, text):
    path = tmp_path / "credentials.env"
    path.write_text(text)
    with pytest.raises(SettingsError) as caught:
        read_openai_key_file(path)
    assert text not in str(caught.value)
