"""Nominal identifier contracts for Talent Stream domain boundaries.

Runtime values remain strings to preserve compatibility with the existing MongoDB
schema. NewType prevents accidental conceptual mixing in typed code without
changing persisted identifiers.
"""
from typing import NewType

UserId = NewType("UserId", str)
CandidateId = NewType("CandidateId", str)
OrganizationId = NewType("OrganizationId", str)
RecruiterUserId = NewType("RecruiterUserId", str)
HiringCompanyId = NewType("HiringCompanyId", str)
MembershipId = NewType("MembershipId", str)
MandateId = NewType("MandateId", str)

CandidateProfileId = NewType("CandidateProfileId", str)
CandidatePreferencesId = NewType("CandidatePreferencesId", str)
RoleDNAId = NewType("RoleDNAId", str)
OpportunitySpecId = NewType("OpportunitySpecId", str)
TalentStreamId = NewType("TalentStreamId", str)
IntentEventId = NewType("IntentEventId", str)
ContactRequestId = NewType("ContactRequestId", str)
GrantId = NewType("GrantId", str)
DocumentId = NewType("DocumentId", str)

IdempotencyKey = NewType("IdempotencyKey", str)
CorrelationId = NewType("CorrelationId", str)
CausationId = NewType("CausationId", str)
