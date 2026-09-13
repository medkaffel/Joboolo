"""Pure native Own Job source classification shared by B2 and B3."""
from collections.abc import Mapping


NON_NATIVE_JOB_MARKERS = (
    "partner_id",
    "campaign_id",
    "external_url",
    "external_ref",
)


def own_job_source_violation(source) -> str | None:
    """Return a fixed reason when a raw Job cannot be a native Own Job.

    The classifier deliberately knows nothing about B2 mapping versions. Empty
    ``source`` and absent/None external markers retain the historical B2
    behavior; every populated external marker is rejected.
    """
    if not isinstance(source, Mapping):
        return "invalid_source"
    if "is_partner" in source and type(source["is_partner"]) is not bool:
        return "invalid_is_partner"
    if source.get("is_partner") is True:
        return "non_native_source"
    if any(source.get(marker) is not None for marker in NON_NATIVE_JOB_MARKERS):
        return "non_native_source"
    if source.get("source") not in (None, ""):
        return "non_native_source"
    return None
