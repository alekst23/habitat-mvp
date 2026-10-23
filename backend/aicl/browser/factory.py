"""Compose the private runtime and durable owner request service."""
from aicl.browser.service import BrowserBroker


def browser_broker(ctx, requests=None):
    if requests is None:
        from aicl.owner_requests.factory import owner_request_service
        requests = owner_request_service(ctx)
    return BrowserBroker(ctx, requests)
