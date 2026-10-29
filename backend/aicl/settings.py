"""Settings: validation of every row of the consolidated configuration table (E11-1)."""

from __future__ import annotations

import base64
import re
from typing import Mapping
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, SecretStr, model_validator


class SettingsError(Exception):
    """Startup failure; names the variable, never its value."""

    def __init__(self, variable: str, message: str) -> None:
        super().__init__(f"{variable}: {message}")
        self.variable = variable


def validate_mock_payment_settings(environment: str, api_url: str, token: str) -> None:
    """Keep the optional HTTP fixture isolated from remote services and production."""
    if (api_url or token) and environment not in ("development", "test"):
        raise SettingsError("AICL_MOCK_PAYMENT_API_URL", "is available only in development or test")
    if api_url:
        match = re.fullmatch(r"http://127\.0\.0\.1:([1-9][0-9]{0,4})", api_url)
        if not match or int(match.group(1)) > 65535:
            raise SettingsError("AICL_MOCK_PAYMENT_API_URL", "must be exactly http://127.0.0.1:PORT")
        if not token:
            raise SettingsError("AICL_MOCK_PAYMENT_TOKEN", "is required with the mock payment API")
    if token and (not 24 <= len(token) <= 1024 or not token.isascii()
                  or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)):
        raise SettingsError("AICL_MOCK_PAYMENT_TOKEN", "must contain 24–1024 ASCII characters without whitespace")


def validate_public_base_url(environment: str, base_url: str) -> None:
    """Accept a single origin, never a credential-bearing URL or callback path."""
    try:
        parsed = urlparse(base_url)
        port = parsed.port
        valid = (
            parsed.scheme in ("http", "https") and bool(parsed.hostname)
            and not parsed.username and not parsed.password and "@" not in parsed.netloc
            and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
            and "?" not in base_url and "#" not in base_url and "\\" not in base_url
            and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in base_url)
            and (port is None or 1 <= port <= 65535)
        )
    except ValueError:
        valid = False
    if not valid:
        raise SettingsError("AICL_PUBLIC_BASE_URL", "must be a clean http(s) origin without credentials, path, query or fragment")
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme == "http" and not (environment in ("test", "development") and local):
        raise SettingsError("AICL_PUBLIC_BASE_URL", "must use https outside local test or development")


class Settings(BaseModel):
    """Typed settings. Defaults mirror architecture.md; required variables have no default."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    environment: str
    test_mode: bool = False
    hosted_workflow: bool = False
    judge_demo_mode: bool = False
    local_private_entry: bool = False
    access_link_token: SecretStr = SecretStr("")
    workflow_execution_mode: str = "local"
    render_max_spend_micro_usd: int = 1_000_000
    render_max_dispatches: int = 100
    scheduler_token: SecretStr = SecretStr("")
    worker_token: SecretStr = SecretStr("")
    browser_service_url: str = ""
    browser_service_token: SecretStr = SecretStr("")
    waitlist_webhook_url: str = ""
    waitlist_webhook_token: SecretStr = SecretStr("")
    public_base_url: str = "http://127.0.0.1:4173"
    database_url: str
    session_secret: str
    identity_hmac_key: str
    secret_encryption_key: str
    price_table_path: str
    session_ttl_seconds: int = 28800
    magic_link_ttl_seconds: int = 900
    confirmation_ttl_seconds: int = 300
    reconcile_interval_seconds: int = 60
    hold_stale_seconds: int = 900
    executor_timeout_seconds: int = 30
    provider_mode: str = "fake"
    executor_mode: str = "fake"
    chat_model_mode: str = "fake"
    assistant_max_spend_micro_usd: int = 1_000_000
    studio_license_key: SecretStr = SecretStr("")
    inference_mode: str = "mock"
    agent_runtime_mode: str = "off"
    openai_api_key: SecretStr = SecretStr("")
    brave_search_api_key: SecretStr = SecretStr("")
    research_worker_image: str = ""
    research_provider_account: str = ""
    research_credential_binding: str = ""
    inference_max_spend_micro_usd: int = 1_000_000
    payment_api_url: str = ""
    payment_token: SecretStr = SecretStr("")
    payment_mode: str = "mock"
    paypal_client_id: str = ""
    paypal_client_secret: SecretStr = SecretStr("")
    paypal_merchant_id: str = ""
    paypal_purchase_client_id: str = ""
    paypal_purchase_client_secret: SecretStr = SecretStr("")
    paypal_purchase_merchant_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from: str = ""

    @property
    def private_entry_enabled(self) -> bool:
        """Share private-link authentication without enabling hosted services locally."""
        return self.judge_demo_mode or self.local_private_entry

    @property
    def workflow_enabled(self) -> bool:
        """Product workflow pages are separate from the guarded test helpers."""
        return self.environment in ("development", "test") or self.hosted_workflow

    @property
    def waitlist_enabled(self) -> bool:
        return bool(self.waitlist_webhook_url and self.waitlist_webhook_token.get_secret_value())

    @model_validator(mode="after")
    def validate_waitlist_configuration(self) -> "Settings":
        url, token = self.waitlist_webhook_url, self.waitlist_webhook_token.get_secret_value()
        if not url and not token:
            return self
        if re.fullmatch(r"https://script\.google\.com/macros/s/[A-Za-z0-9_-]+/exec", url) is None:
            raise SettingsError("AICL_WAITLIST_WEBHOOK_URL", "must be the Google Apps Script HTTPS deployment URL ending in /exec")
        if re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token) is None or token.startswith(("CHANGE_ME", "YOUR_")):
            raise SettingsError("AICL_WAITLIST_WEBHOOK_TOKEN", "must contain 32–128 non-placeholder URL-safe characters")
        if token in (self.session_secret, self.identity_hmac_key, self.secret_encryption_key,
                     self.access_link_token.get_secret_value(), self.scheduler_token.get_secret_value(),
                     self.worker_token.get_secret_value(), self.browser_service_token.get_secret_value()):
            raise SettingsError("AICL_WAITLIST_WEBHOOK_TOKEN", "must differ from session, identity, encryption and machine keys")
        return self

    @model_validator(mode="after")
    def validate_hosted_configuration(self) -> "Settings":
        if self.environment not in ("development", "test", "production"):
            raise SettingsError("AICL_ENVIRONMENT", "must be development, test or production")
        if self.test_mode and self.environment != "test":
            raise SettingsError("AICL_TEST_MODE", "1 is valid only with AICL_ENVIRONMENT=test")
        if self.local_private_entry:
            public = urlparse(self.public_base_url)
            if (self.environment != "test" or not self.test_mode or self.hosted_workflow
                    or self.judge_demo_mode or self.workflow_execution_mode != "local"
                    or self.payment_mode != "mock" or public.scheme != "http"
                    or public.hostname != "127.0.0.1"):
                raise SettingsError("AICL_LOCAL_PRIVATE_ENTRY", "requires loopback HTTP test mode with local execution and mock payments")
        if self.hosted_workflow and self.environment != "production":
            raise SettingsError("AICL_HOSTED_WORKFLOW", "requires production authentication with test mode disabled")
        if self.judge_demo_mode and (not self.hosted_workflow or self.environment != "production" or self.test_mode):
            raise SettingsError("AICL_JUDGE_DEMO_MODE", "requires the hosted production profile with test mode disabled")
        if self.judge_demo_mode and self.payment_mode != "paypal_sandbox":
            raise SettingsError("AICL_PAYMENT_MODE", "judge demonstration requires PayPal Sandbox")
        access_token = self.access_link_token.get_secret_value()
        if self.private_entry_enabled or access_token:
            if (re.fullmatch(r"[A-Za-z0-9_-]{32,128}", access_token) is None
                    or access_token.startswith(("CHANGE_ME", "YOUR_"))):
                raise SettingsError("AICL_ACCESS_LINK_TOKEN", "must contain 32–128 non-placeholder URL-safe characters")
            if access_token in (self.session_secret, self.identity_hmac_key, self.secret_encryption_key,
                                self.scheduler_token.get_secret_value(), self.worker_token.get_secret_value()):
                raise SettingsError("AICL_ACCESS_LINK_TOKEN", "must differ from session, identity, encryption and machine keys")
        if type(self.render_max_spend_micro_usd) is not int or not 1 <= self.render_max_spend_micro_usd <= 10_000_000:
            raise SettingsError("AICL_RENDER_MAX_SPEND_MICRO_USD", "must be between 1 and 10000000")
        if type(self.render_max_dispatches) is not int or not 1 <= self.render_max_dispatches <= 1000:
            raise SettingsError("AICL_RENDER_MAX_DISPATCHES", "must be between 1 and 1000")
        if self.workflow_execution_mode not in ("local", "render"):
            raise SettingsError("AICL_WORKFLOW_EXECUTION_MODE", "must be local or render")
        if self.workflow_execution_mode == "render" and not self.hosted_workflow:
            raise SettingsError("AICL_WORKFLOW_EXECUTION_MODE", "render requires AICL_HOSTED_WORKFLOW=1")
        if self.hosted_workflow:
            validate_public_base_url(self.environment, self.public_base_url)
            if not self.smtp_host and not self.judge_demo_mode:
                raise SettingsError("AICL_SMTP_HOST", "is required for hosted sign-in")
            if not self.smtp_from and not self.judge_demo_mode:
                raise SettingsError("AICL_SMTP_FROM", "is required for hosted sign-in")
        credentials = (
            ("AICL_SCHEDULER_TOKEN", self.scheduler_token.get_secret_value()),
            ("AICL_WORKER_TOKEN", self.worker_token.get_secret_value()),
        )
        for name, value in credentials:
            if not value and self.workflow_execution_mode != "render":
                continue
            if (not 32 <= len(value) <= 1024 or not value.isascii()
                    or value.startswith(("CHANGE_ME", "YOUR_"))
                    or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value)):
                raise SettingsError(name, "must contain 32–1024 non-placeholder ASCII characters without whitespace")
            if value in (self.session_secret, self.identity_hmac_key, self.secret_encryption_key):
                raise SettingsError(name, "must differ from owner session and encryption keys")
        if credentials[0][1] and credentials[0][1] == credentials[1][1]:
            raise SettingsError("AICL_WORKER_TOKEN", "must differ from AICL_SCHEDULER_TOKEN")
        return self

    @model_validator(mode="after")
    def validate_browser_configuration(self) -> "Settings":
        url, token = self.browser_service_url, self.browser_service_token.get_secret_value()
        if not url and not token:
            return self
        if not url:
            raise SettingsError("AICL_BROWSER_SERVICE_URL", "is required with the browser service token")
        try:
            parsed = urlparse(url)
            host, port = parsed.hostname or "", parsed.port
            private = bool(re.fullmatch(r"[a-z][a-z0-9-]{0,62}(?:\.internal)?", host)) and host != "localhost"
            local = self.environment in ("development", "test") and host in ("127.0.0.1", "localhost", "::1")
            valid = (parsed.scheme == "http" and (private or local)
                     and not parsed.username and not parsed.password and "@" not in parsed.netloc
                     and parsed.path in ("", "/") and not parsed.query and not parsed.fragment
                     and "?" not in url and "#" not in url and "\\" not in url
                     and not any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in url)
                     and (port is None or 1 <= port <= 65535))
        except ValueError:
            valid = False
        if not valid:
            raise SettingsError("AICL_BROWSER_SERVICE_URL", "must be a clean private Render http origin, or loopback in development/test")
        if (not 32 <= len(token) <= 1024 or not token.isascii() or token.startswith(("CHANGE_ME", "YOUR_"))
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in token)):
            raise SettingsError("AICL_BROWSER_SERVICE_TOKEN", "must contain 32–1024 non-placeholder ASCII characters without whitespace")
        others = (self.session_secret, self.identity_hmac_key, self.secret_encryption_key,
                  self.worker_token.get_secret_value(), self.scheduler_token.get_secret_value(),
                  self.access_link_token.get_secret_value(), self.openai_api_key.get_secret_value(),
                  self.payment_token.get_secret_value(), self.paypal_client_secret.get_secret_value(),
                  self.paypal_purchase_client_secret.get_secret_value())
        if token in others:
            raise SettingsError("AICL_BROWSER_SERVICE_TOKEN", "must differ from owner, worker, payment and model credentials")
        return self

    @model_validator(mode="after")
    def validate_inference_configuration(self) -> "Settings":
        if self.research_worker_image and not re.fullmatch(r"sha256:[0-9a-f]{64}", self.research_worker_image):
            raise SettingsError("AICL_RESEARCH_WORKER_IMAGE", "must be an immutable local Docker image ID")
        if self.brave_search_api_key.get_secret_value():
            key = self.brave_search_api_key.get_secret_value()
            if not key.isascii() or not 12 <= len(key) <= 1024 or any(ord(c) < 33 or ord(c) == 127 for c in key):
                raise SettingsError("BRAVE_SEARCH_API_KEY", "must be a bounded ASCII credential without whitespace")
            for label, value in (("AICL_RESEARCH_PROVIDER_ACCOUNT", self.research_provider_account),
                                 ("AICL_RESEARCH_CREDENTIAL_BINDING", self.research_credential_binding)):
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value):
                    raise SettingsError(label, "must identify the operator-approved provider account and credential version")
        if self.agent_runtime_mode not in ("off", "openai"):
            raise SettingsError("AICL_AGENT_RUNTIME_MODE", "must be off or openai")
        if self.agent_runtime_mode == "openai":
            if self.environment not in ("development", "test") or self.workflow_execution_mode != "local":
                raise SettingsError("AICL_AGENT_RUNTIME_MODE", "requires local development or test; production storage is not enabled")
            if self.chat_model_mode != "openai":
                raise SettingsError("AICL_CHAT_MODEL_MODE", "must be openai when the interactive agent runtime is enabled")
        if self.chat_model_mode not in ("fake", "openai"):
            raise SettingsError("AICL_CHAT_MODEL_MODE", "must be fake or openai")
        if not 1 <= self.assistant_max_spend_micro_usd <= 10_000_000:
            raise SettingsError("AICL_ASSISTANT_MAX_SPEND_MICRO_USD", "must be between 1 and 10000000")
        if self.inference_mode not in ("mock", "openai"):
            raise SettingsError("AICL_INFERENCE_MODE", "must be mock or openai")
        if not 1 <= self.inference_max_spend_micro_usd <= 10_000_000:
            raise SettingsError("AICL_INFERENCE_MAX_SPEND_MICRO_USD", "must be between 1 and 10000000")
        if self.inference_mode == "mock" and self.chat_model_mode == "fake":
            return self
        if not self.workflow_enabled:
            raise SettingsError("AICL_INFERENCE_MODE", "openai requires development, test or explicit hosted workflow mode")
        key = self.openai_api_key.get_secret_value()
        if not key:
            raise SettingsError("OPENAI_API_KEY", "is required for openai inference")
        if (len(key) < 12 or len(key) > 1024 or not key.isascii()
                or key.startswith(("CHANGE_ME", "YOUR_"))
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in key)):
            raise SettingsError("OPENAI_API_KEY", "must be a non-placeholder ASCII API key without whitespace")
        return self

    @model_validator(mode="after")
    def validate_payment_configuration(self) -> "Settings":
        """The direct constructor and environment entry point share payment guards."""
        validate_public_base_url(self.environment, self.public_base_url)
        if self.payment_mode not in ("mock", "paypal_sandbox"):
            raise SettingsError("AICL_PAYMENT_MODE", "must be mock or paypal_sandbox; live payments are not supported")
        validate_mock_payment_settings(self.environment, self.payment_api_url, self.payment_token.get_secret_value())
        credentials = (
            ("AICL_PAYPAL_CLIENT_ID", self.paypal_client_id),
            ("AICL_PAYPAL_CLIENT_SECRET", self.paypal_client_secret.get_secret_value()),
            ("AICL_PAYPAL_MERCHANT_ID", self.paypal_merchant_id),
            ("AICL_PAYPAL_PURCHASE_CLIENT_ID", self.paypal_purchase_client_id),
            ("AICL_PAYPAL_PURCHASE_CLIENT_SECRET", self.paypal_purchase_client_secret.get_secret_value()),
            ("AICL_PAYPAL_PURCHASE_MERCHANT_ID", self.paypal_purchase_merchant_id),
        )
        if self.payment_mode == "mock":
            if any(value for _, value in credentials):
                raise SettingsError("AICL_PAYMENT_MODE", "must be paypal_sandbox when PayPal credentials are configured")
            return self
        if not self.workflow_enabled:
            raise SettingsError("AICL_PAYMENT_MODE", "paypal_sandbox requires development, test or explicit hosted workflow mode")
        if self.payment_api_url or self.payment_token.get_secret_value():
            raise SettingsError("AICL_PAYMENT_MODE", "paypal_sandbox cannot be combined with mock payment transport settings")
        required = credentials[:3]
        if any(value for _, value in credentials[3:]):
            required += credentials[3:]
        for name, value in required:
            if not value:
                raise SettingsError(name, "is required for PayPal Sandbox")
            if value.startswith("CHANGE_ME") or value.startswith("YOUR_"):
                raise SettingsError(name, "is a placeholder; set the Sandbox credential")
            if not value.isascii() or len(value) > 2048 or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
                raise SettingsError(name, "must contain ASCII characters without whitespace")
            if name.endswith("MERCHANT_ID") and re.fullmatch(r"[A-Z0-9]{1,36}", value) is None:
                raise SettingsError(name, "must be the Sandbox account's uppercase alphanumeric merchant ID")
        return self

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Settings":
        """Validate every row; raise SettingsError (fail startup) on any invalid or missing value."""
        def get(name: str, default: str | None = None) -> str:
            value = env.get(name, default)
            if value is None or value == "":
                if default is not None:
                    return default
                raise SettingsError(name, "is required")
            return value

        def integer(name: str, default: int, low: int, high: int) -> int:
            raw = env.get(name)
            if raw is None or raw == "":
                return default
            try:
                value = int(raw)
            except ValueError:
                raise SettingsError(name, "must be an integer") from None
            if not low <= value <= high:
                raise SettingsError(name, f"must be between {low} and {high}")
            return value

        environment = get("AICL_ENVIRONMENT")
        if environment not in ("development", "test", "production"):
            raise SettingsError("AICL_ENVIRONMENT", "must be development, test or production")
        flag = env.get("AICL_TEST_MODE", "0") or "0"
        if flag not in ("0", "1"):
            raise SettingsError("AICL_TEST_MODE", "must be 0 or 1")
        if flag == "1" and environment != "test":
            raise SettingsError("AICL_TEST_MODE", "1 is valid only with AICL_ENVIRONMENT=test")
        hosted_flag = env.get("AICL_HOSTED_WORKFLOW", "0") or "0"
        if hosted_flag not in ("0", "1"):
            raise SettingsError("AICL_HOSTED_WORKFLOW", "must be 0 or 1")
        judge_flag = env.get("AICL_JUDGE_DEMO_MODE", "0") or "0"
        if judge_flag not in ("0", "1"):
            raise SettingsError("AICL_JUDGE_DEMO_MODE", "must be 0 or 1")
        local_entry_flag = env.get("AICL_LOCAL_PRIVATE_ENTRY", "0") or "0"
        if local_entry_flag not in ("0", "1"):
            raise SettingsError("AICL_LOCAL_PRIVATE_ENTRY", "must be 0 or 1")
        # Studio is a reporting surface. Legacy enablement must fail closed;
        # an environment change cannot introduce a model path outside AICL.
        if (env.get("AICL_STUDIO_AI_ENABLED") or "0") != "0":
            raise SettingsError("AICL_STUDIO_AI_ENABLED", "Studio AI is hard disabled by policy; remove this setting or use 0")

        payment_api_url = env.get("AICL_MOCK_PAYMENT_API_URL") or ""
        payment_token = env.get("AICL_MOCK_PAYMENT_TOKEN") or ""
        validate_mock_payment_settings(environment, payment_api_url, payment_token)

        base_url = get("AICL_PUBLIC_BASE_URL", "http://127.0.0.1:4173")
        validate_public_base_url(environment, base_url)

        database_url = get("AICL_DATABASE_URL")
        if not database_url.startswith("sqlite:///") or len(database_url) <= len("sqlite:///"):
            raise SettingsError("AICL_DATABASE_URL", "must be sqlite:///path")

        placeholders = ("CHANGE_ME_32_BYTES_MINIMUM", "CHANGE_ME_IDENTITY_32_BYTES_MIN", "CHANGE_ME_BASE64_32_BYTES")
        session_secret = get("AICL_SESSION_SECRET")
        identity_key = get("AICL_IDENTITY_HMAC_KEY")
        encryption_key = get("AICL_SECRET_ENCRYPTION_KEY")
        for name, value in (("AICL_SESSION_SECRET", session_secret), ("AICL_IDENTITY_HMAC_KEY", identity_key),
                            ("AICL_SECRET_ENCRYPTION_KEY", encryption_key)):
            if value in placeholders or value.startswith("CHANGE_ME"):
                raise SettingsError(name, "is a placeholder; set a real secret")
        if len(session_secret.encode()) < 32:
            raise SettingsError("AICL_SESSION_SECRET", "must be at least 32 bytes")
        if len(identity_key.encode()) < 32:
            raise SettingsError("AICL_IDENTITY_HMAC_KEY", "must be at least 32 bytes")
        if identity_key == session_secret:
            raise SettingsError("AICL_IDENTITY_HMAC_KEY", "must differ from AICL_SESSION_SECRET")
        try:
            decoded = base64.b64decode(encryption_key, validate=True)
        except ValueError:
            raise SettingsError("AICL_SECRET_ENCRYPTION_KEY", "must be base64") from None
        if len(decoded) != 32:
            raise SettingsError("AICL_SECRET_ENCRYPTION_KEY", "must be base64 of exactly 32 bytes")

        modes = {}
        for name, key, extra in (("AICL_PROVIDER_MODE", "provider_mode", "; provider enablement is not recorded"),
                                 ("AICL_EXECUTOR_MODE", "executor_mode", "")):
            value = env.get(name) or "fake"
            if value != "fake":
                raise SettingsError(name, "only fake is accepted" + extra)
            modes[key] = value

        executor_timeout = integer("AICL_EXECUTOR_TIMEOUT_SECONDS", 30, 1, 300)
        reconcile = integer("AICL_RECONCILE_INTERVAL_SECONDS", 60, 5, 3600)
        hold_stale = integer("AICL_HOLD_STALE_SECONDS", 900, 60, 86400)
        if hold_stale <= executor_timeout + reconcile:
            raise SettingsError("AICL_HOLD_STALE_SECONDS", "must exceed executor timeout plus reconcile interval")
        return cls(
            environment=environment, test_mode=flag == "1", public_base_url=base_url, database_url=database_url,
            hosted_workflow=hosted_flag == "1",
            judge_demo_mode=judge_flag == "1",
            local_private_entry=local_entry_flag == "1",
            access_link_token=SecretStr(env.get("AICL_ACCESS_LINK_TOKEN") or ""),
            workflow_execution_mode=env.get("AICL_WORKFLOW_EXECUTION_MODE") or "local",
            render_max_spend_micro_usd=integer("AICL_RENDER_MAX_SPEND_MICRO_USD", 1_000_000, 1, 10_000_000),
            render_max_dispatches=integer("AICL_RENDER_MAX_DISPATCHES", 100, 1, 1000),
            scheduler_token=SecretStr(env.get("AICL_SCHEDULER_TOKEN") or ""),
            worker_token=SecretStr(env.get("AICL_WORKER_TOKEN") or ""),
            browser_service_url=env.get("AICL_BROWSER_SERVICE_URL") or "",
            browser_service_token=SecretStr(env.get("AICL_BROWSER_SERVICE_TOKEN") or ""),
            waitlist_webhook_url=env.get("AICL_WAITLIST_WEBHOOK_URL") or "",
            waitlist_webhook_token=SecretStr(env.get("AICL_WAITLIST_WEBHOOK_TOKEN") or ""),
            session_secret=session_secret, identity_hmac_key=identity_key, secret_encryption_key=encryption_key,
            price_table_path=get("AICL_PRICE_TABLE_PATH"),
            session_ttl_seconds=integer("AICL_SESSION_TTL_SECONDS", 28800, 300, 604800),
            magic_link_ttl_seconds=integer("AICL_MAGIC_LINK_TTL_SECONDS", 900, 60, 3600),
            confirmation_ttl_seconds=integer("AICL_CONFIRMATION_TTL_SECONDS", 300, 30, 3600),
            reconcile_interval_seconds=reconcile, hold_stale_seconds=hold_stale,
            executor_timeout_seconds=executor_timeout,
            inference_mode=env.get("AICL_INFERENCE_MODE") or "mock",
            agent_runtime_mode=env.get("AICL_AGENT_RUNTIME_MODE") or "off",
            chat_model_mode=env.get("AICL_CHAT_MODEL_MODE") or "fake",
            assistant_max_spend_micro_usd=integer("AICL_ASSISTANT_MAX_SPEND_MICRO_USD", 1_000_000, 1, 10_000_000),
            studio_license_key=SecretStr(env.get("AICL_STUDIO_LICENSE_KEY") or ""),
            openai_api_key=SecretStr(env.get("OPENAI_API_KEY") or ""),
            brave_search_api_key=SecretStr(env.get("BRAVE_SEARCH_API_KEY") or ""),
            research_worker_image=env.get("AICL_RESEARCH_WORKER_IMAGE") or "",
            research_provider_account=env.get("AICL_RESEARCH_PROVIDER_ACCOUNT") or "",
            research_credential_binding=env.get("AICL_RESEARCH_CREDENTIAL_BINDING") or "",
            inference_max_spend_micro_usd=integer("AICL_INFERENCE_MAX_SPEND_MICRO_USD", 1_000_000, 1, 10_000_000),
            payment_api_url=payment_api_url, payment_token=SecretStr(payment_token),
            payment_mode=env.get("AICL_PAYMENT_MODE") or "mock",
            paypal_client_id=env.get("AICL_PAYPAL_CLIENT_ID") or "",
            paypal_client_secret=SecretStr(env.get("AICL_PAYPAL_CLIENT_SECRET") or ""),
            paypal_merchant_id=env.get("AICL_PAYPAL_MERCHANT_ID") or "",
            paypal_purchase_client_id=env.get("AICL_PAYPAL_PURCHASE_CLIENT_ID") or "",
            paypal_purchase_client_secret=SecretStr(env.get("AICL_PAYPAL_PURCHASE_CLIENT_SECRET") or ""),
            paypal_purchase_merchant_id=env.get("AICL_PAYPAL_PURCHASE_MERCHANT_ID") or "",
            smtp_host=env.get("AICL_SMTP_HOST") or "", smtp_port=integer("AICL_SMTP_PORT", 587, 1, 65535),
            smtp_username=env.get("AICL_SMTP_USERNAME") or "", smtp_password=env.get("AICL_SMTP_PASSWORD") or "",
            smtp_from=env.get("AICL_SMTP_FROM") or "", **modes)
