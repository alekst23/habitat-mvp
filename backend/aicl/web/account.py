"""Shared account presentation; labels never grant access or identify an owner."""


def sidebar_context(ctx, auth) -> dict[str, str]:
    return {
        "account_name": auth.display_name or ("Judge" if ctx.settings.judge_demo_mode else "Owner"),
        "csrf": ctx.csrf_verifier.token_for(auth.session_id),
    }
