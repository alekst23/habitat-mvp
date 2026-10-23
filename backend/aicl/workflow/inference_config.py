"""Explicit opt-in for local demos; API keys stay on the control-plane server."""

from __future__ import annotations

import os
import re
from pathlib import Path

from aicl.settings import Settings, SettingsError


def add_inference_arguments(parser) -> None:
    parser.add_argument("--chat", choices=("fake", "openai"), default="fake",
                        help="openai enables the interviewing and monitoring assistant")
    parser.add_argument("--assistant-max-spend-micro-usd", type=int, default=1_000_000,
                        help="separate persistent assistant API allowance (default 1000000 = $1)")
    parser.add_argument("--inference", choices=("mock", "openai"), default="mock",
                        help="openai calls GPT-6 Sol for campaign plans and reports; default is mock")
    parser.add_argument("--inference-key-file", type=Path,
                        help="read OPENAI_API_KEY from a literal KEY=value file; never executed")
    parser.add_argument("--inference-max-spend-micro-usd", type=int, default=1_000_000,
                        help="persistent per-database API ceiling in micro-USD (default 1000000 = $1)")


def read_openai_key_file(path: Path) -> str:
    """Read a single named secret without sourcing a .env or logging its content."""
    try:
        with path.open("rb") as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise SettingsError("--inference-key-file", "must be at most 64 KiB")
        lines = data.decode("utf-8").splitlines()
    except (OSError, UnicodeError):
        raise SettingsError("--inference-key-file", "could not read a UTF-8 credentials file") from None
    found = None
    for line in lines:
        match = re.fullmatch(r"\s*(?:export\s+)?OPENAI_API_KEY\s*=\s*(.*?)\s*", line)
        if not match:
            continue  # A shared .env can contain unrelated entries; none are executed.
        if found is not None:
            raise SettingsError("OPENAI_API_KEY", "appears more than once in the credentials file")
        found = match[1]
        if found.startswith(("'", '"')):
            if len(found) < 2 or found[-1] != found[0]:
                raise SettingsError("OPENAI_API_KEY", "must have matching quotes")
            found = found[1:-1]
        if any(c in found for c in ("$", "`", "\\", "\x00")):
            raise SettingsError("OPENAI_API_KEY", "must be literal, without shell expressions or escapes")
    if not found:
        raise SettingsError("OPENAI_API_KEY", "was not found in the credentials file")
    return found


def with_inference_settings(settings: Settings, args) -> Settings:
    chat_mode = getattr(args, "chat", "fake")
    if args.inference == "mock" and chat_mode == "fake" and args.inference_key_file:
        raise SettingsError("--inference", "choose openai when supplying an inference key file")
    key = ""
    if args.inference == "openai" or chat_mode == "openai":
        key = (read_openai_key_file(args.inference_key_file) if args.inference_key_file
               else os.environ.get("OPENAI_API_KEY", ""))
    return Settings.model_validate({**settings.model_dump(), "inference_mode": args.inference,
        "chat_model_mode": chat_mode,
        "assistant_max_spend_micro_usd": getattr(args, "assistant_max_spend_micro_usd", 1_000_000),
        "openai_api_key": key, "inference_max_spend_micro_usd": args.inference_max_spend_micro_usd})


def inference_startup_message(settings: Settings) -> str:
    assistant = (f" GPT-6 Sol owner assistant enabled; separate allowance ${settings.assistant_max_spend_micro_usd / 1_000_000:.2f}."
                 if settings.chat_model_mode == "openai" else "")
    if settings.inference_mode == "mock":
        return "Workflow inference is simulated." + assistant if assistant else "Inference is simulated; no model API calls."
    return ("GPT-6 Sol inference enabled for campaign plans and reports. "
            f"API spending ceiling: ${settings.inference_max_spend_micro_usd / 1_000_000:.2f} per database; "
            "AICL budgets and service credit also apply. Advertising remains simulated." + assistant)
