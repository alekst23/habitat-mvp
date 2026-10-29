"""Bounded editable draft; publication performs the stricter readiness checks."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from aicl.agent_runtime.contracts import RunDefinition
from aicl.control.errors import AiclError
from aicl.control.instances import MAX_LIMIT_MICRO_USD


class WorkspaceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class WorkspaceLimits(WorkspaceModel):
    inference_daily_micro_usd: int = Field(default=0, ge=0, le=MAX_LIMIT_MICRO_USD)
    inference_monthly_micro_usd: int = Field(default=0, ge=0, le=MAX_LIMIT_MICRO_USD)
    compute_daily_micro_usd: int = Field(default=0, ge=0, le=MAX_LIMIT_MICRO_USD)
    compute_monthly_micro_usd: int = Field(default=0, ge=0, le=MAX_LIMIT_MICRO_USD)


class WorkspaceDeliverable(WorkspaceModel):
    key: str = Field(default="", max_length=64)
    name: str = Field(default="", max_length=120)
    description: str = Field(default="", max_length=2000)
    criteria: list[str] = Field(default_factory=list, max_length=12)


class PublicResearchDraft(WorkspaceModel):
    """Proposed public disclosures, separate from private task instructions.

    Editing this object is never release authority. Owner approval is stored
    separately and binds its exact canonical digest.
    """
    purpose: str = Field(default="", max_length=500)
    queries: list[str] = Field(default_factory=list, max_length=10)
    source_urls: list[str] = Field(default_factory=list, max_length=20)


class WebAccess(WorkspaceModel):
    """Owner-editable destination scope; applying it releases the visible goal."""
    mode: Literal["off", "allowlist", "blocklist", "all"] = "off"
    domains: list[str] = Field(default_factory=list, max_length=20)


class WorkspaceDraft(WorkspaceModel):
    name: str = Field(default="", max_length=80)
    goal: str = Field(default="", max_length=2000)
    inputs: str = Field(default="", max_length=4000)
    deliverables: list[WorkspaceDeliverable] = Field(default_factory=list, max_length=6)
    tools: list[str] = Field(default_factory=list, max_length=20)
    network_domains: list[str] = Field(default_factory=list, max_length=20)
    public_research: PublicResearchDraft = Field(default_factory=PublicResearchDraft)
    # None preserves historical exact approvals without converting them into a
    # broader standing grant. The UI offers the new policy explicitly on Apply.
    web_access: WebAccess | None = None
    # Absent search policy preserves the previously bundled web permission.
    # Explicit policies allow search and page reads to be controlled separately.
    web_search: WebAccess | None = None
    limits: WorkspaceLimits = Field(default_factory=WorkspaceLimits)
    cadence: Literal["manual", "hourly", "daily"] = "manual"
    timezone: str = Field(default="America/New_York", max_length=80)
    time_of_day: str = Field(default="09:00", max_length=5)


def empty_draft():
    return WorkspaceDraft().model_dump()


def run_definition(draft):
    """The definition validated at application and used by every run trigger."""
    requirements = [{"id": item["key"], "text": item["name"] + "\n" + item["description"]
                     + "\nCompletion criteria:\n" + "\n".join(item["criteria"])} for item in draft["deliverables"]]
    try:
        return RunDefinition(objective=draft["goal"] + ("\n\nSupplied context:\n" + draft["inputs"] if draft["inputs"] else ""),
                             requirements=requirements, allowed_tools=sorted(draft["tools"]))
    except ValidationError:
        raise AiclError("validation_failed", "The requirements exceed the execution limit. Shorten the deliverable description or criteria before applying.") from None
