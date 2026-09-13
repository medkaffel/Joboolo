"""Minimal immutable TS-B3 application source contracts."""
from dataclasses import dataclass
from datetime import datetime

from domains.shared.ids import CandidateId, JobId
from domains.talent_stream.stream_models import nonblank_identifier, utc_millisecond
from models import ApplicationStatus


@dataclass(frozen=True, slots=True, repr=False)
class ApplicationSource:
    application_id: str
    candidate_id: CandidateId
    job_id: JobId
    status: ApplicationStatus
    applied_at: datetime

    def __post_init__(self) -> None:
        nonblank_identifier(self.application_id, "application_id")
        nonblank_identifier(self.candidate_id, "candidate_id")
        nonblank_identifier(self.job_id, "job_id")
        if type(self.status) is not ApplicationStatus:
            raise ValueError("unsupported application status")
        object.__setattr__(
            self,
            "applied_at",
            utc_millisecond(self.applied_at, "applied_at"),
        )


@dataclass(frozen=True, slots=True, repr=False)
class ApplicationSourceCursor:
    applied_at: datetime
    application_id: str

    def __post_init__(self) -> None:
        nonblank_identifier(self.application_id, "application_id")
        object.__setattr__(
            self,
            "applied_at",
            utc_millisecond(self.applied_at, "cursor.applied_at"),
        )
