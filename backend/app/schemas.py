from pydantic import BaseModel, Field


class Deadline(BaseModel):
    title: str
    date: str | None = None
    day: str | None = None
    month: str | None = None
    time: str | None = None
    urgency: str | None = None
    evidence: str | None = None
    ambiguity: str | None = None


class ChecklistItem(BaseModel):
    text: str
    evidence: str | None = None


class Analysis(BaseModel):
    title: str = "Notice analysis"
    summary: str
    summary_evidence: str | None = None
    audience: str = "Not specified in the notice"
    audience_evidence: str | None = None
    deadlines: list[Deadline] = Field(default_factory=list)
    checklist: list[ChecklistItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source_text: str
