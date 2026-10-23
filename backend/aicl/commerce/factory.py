"""One commerce composition for owner pages and payment actions."""

from aicl.commerce.service import MockCommerceService
from aicl.settings import Settings


def commerce_service(ctx) -> MockCommerceService:
    # Revalidate copies too: model_copy(update=...) deliberately skips Pydantic validation.
    settings = Settings.model_validate(ctx.settings.model_dump())
    token = settings.payment_token.get_secret_value()
    if settings.payment_mode == "paypal_sandbox":
        from aicl.commerce.paypal_sandbox import PayPalSandboxAdapter

        return MockCommerceService(
            ctx.db, ctx.clock, settings.hold_stale_seconds,
            payments=PayPalSandboxAdapter(
                client_id=settings.paypal_client_id,
                client_secret=settings.paypal_client_secret.get_secret_value(),
                merchant_id=settings.paypal_merchant_id,
                public_base_url=settings.public_base_url,
                purchase_client_id=settings.paypal_purchase_client_id,
                purchase_client_secret=settings.paypal_purchase_client_secret.get_secret_value(),
                purchase_merchant_id=settings.paypal_purchase_merchant_id,
            ),
        )
    if not settings.payment_api_url:
        return MockCommerceService(ctx.db, ctx.clock, settings.hold_stale_seconds)
    from aicl.commerce.payment_client import HttpMockPaymentAdapter

    return MockCommerceService(
        ctx.db, ctx.clock, settings.hold_stale_seconds,
        payments=HttpMockPaymentAdapter(settings.payment_api_url, token, timeout_seconds=3.0),
    )
