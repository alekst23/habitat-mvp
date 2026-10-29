"""Shared account presentation; labels never grant access or identify an owner."""


def sidebar_context(ctx, auth) -> dict:
    return {
        "account_name": auth.display_name or ("Judge" if ctx.settings.judge_demo_mode else "Owner"),
        "csrf": ctx.csrf_verifier.token_for(auth.session_id),
        "unified_workspace": getattr(ctx, "agent_runtime", None) is not None,
    }
