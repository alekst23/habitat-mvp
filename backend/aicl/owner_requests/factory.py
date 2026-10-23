"""Share the configured workflow, accounting and payment transports."""

from aicl.owner_requests.service import OwnerRequestService
from aicl.workflow.factory import workflow_service


def owner_request_service(ctx):
    service = OwnerRequestService(workflow_service(ctx), browser_enabled=bool(ctx.settings.browser_service_url))
    if service.browser_enabled:
        from aicl.browser.factory import browser_broker
        service.browser_cancel = lambda auth, request_id: browser_broker(ctx, service).cancel(auth, request_id)
    return service
