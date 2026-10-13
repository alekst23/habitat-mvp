# AICL experience technical design

## Contracts

E11-3 owns `CreateInstanceRequest {template_id, name, instructions, enabled_capabilities}` and `CreateInstanceResult`. E11-4 consumes the same request through first-party web-app tools. The canonical service rejects unknown templates/configuration and derives owner/tenant from session context.

E11-5 owns read projections for workspace, instance detail, budget/usage, attachments, lifecycle, gate reasons, and redacted audit history. UI mutations use server-side authenticated requests and return committed state or a structured denial.

## Process topology

Landing routes to magic-link sign-in. The authenticated workspace hosts wizard, chat, connections, list, and detail routes. Wizard and chat call the same creation service; chat cannot carry OAuth tokens or bypass confirmation/validation.

## Configuration

Magic-link delivery configuration is secret-referenced and startup fails outside test mode when absent. UI never accepts a tenant ID. Browser verification uses test email capture only in test mode.
