"""Pure Mongo metadata comparisons; no client, I/O or document inspection.

Callers supply listCollections records and index_information snapshots. A report
is a point-in-time deployment preflight, never an authorization decision or a
substitute for migration-specific document validation. Diagnostics contain only
fixed codes and manifest positions, never server-supplied names or values.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class IndexRequirement:
    name: str
    keys: tuple[tuple[str, int], ...]
    critical: bool
    unique: bool = False
    partial_filter: Mapping[str, Any] | None = None
    # None means inherit the collection default, as in the shipped migrations.
    collation: Mapping[str, Any] | None = None
    sparse: bool = False
    hidden: bool = False
    expire_after_seconds: int | None = None


@dataclass(frozen=True)
class CollectionRequirement:
    name: str
    indexes: tuple[IndexRequirement, ...]
    ordinary: bool = True
    simple_collation: bool = False
    forbid_ttl: bool = True
    forbid_extra_indexes: bool = False


@dataclass(frozen=True)
class Diagnostic:
    severity: str
    code: str
    collection_position: int
    # -1 denotes a collection-wide invariant, 0 the native _id_ index.
    index_position: int = -1


@dataclass(frozen=True)
class VerificationReport:
    diagnostics: tuple[Diagnostic, ...]

    @property
    def ok(self) -> bool:
        return not any(item.severity == "error" for item in self.diagnostics)


def _equal(left: Any, right: Any) -> bool:
    """BSON-like structural equality without treating True as the integer 1."""
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return left.keys() == right.keys() and all(
            _equal(left[key], right[key]) for key in left
        )
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_equal(a, b) for a, b in zip(left, right))
    return type(left) is type(right) and left == right


def _collation(value: Any) -> Any:
    # Mongo omits simple collation. Keep all explicit non-simple options,
    # including the server's ICU version: do not normalize away semantic drift.
    return {"locale": "simple"} if value is None else value


def compare_index(
    requirement: IndexRequirement,
    metadata: Mapping[str, Any],
    collection_collation: Mapping[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return fixed mismatch codes only; ordered keys are never sorted."""
    if not isinstance(metadata, Mapping):
        return ("invalid_index_metadata",)
    mismatches = []
    if not _equal(metadata.get("key"), requirement.keys):
        mismatches.append("keys")
    native = requirement.name == "_id_"
    if not _equal(metadata.get("unique", native), requirement.unique):
        mismatches.append("unique")
    for option, expected in (("sparse", requirement.sparse), ("hidden", requirement.hidden)):
        if not _equal(metadata.get(option, False), expected):
            mismatches.append(option)
    if ("partialFilterExpression" in metadata) != (requirement.partial_filter is not None) or not _equal(
        metadata.get("partialFilterExpression"), requirement.partial_filter
    ):
        mismatches.append("partial_filter")
    if ("expireAfterSeconds" in metadata) != (requirement.expire_after_seconds is not None) or not _equal(
        metadata.get("expireAfterSeconds"), requirement.expire_after_seconds
    ):
        mismatches.append("ttl")
    expected_collation = _collation(
        requirement.collation if requirement.collation is not None else collection_collation
    )
    # Persisted index metadata omits collation for a binary (simple) index,
    # even when the collection default is non-simple. Inheritance applies to
    # the expected migration definition, not to the observed index snapshot.
    actual_collation = _collation(metadata.get("collation"))
    if not _equal(actual_collation, expected_collation):
        mismatches.append("collation")
    # v/ns/name are server bookkeeping; other unmodelled options cannot silently
    # turn an incompatible definition into an exact match.
    if set(metadata) - {"v", "ns", "name", "key", "unique", "sparse", "hidden",
                        "partialFilterExpression", "expireAfterSeconds", "collation"}:
        mismatches.append("unexpected_options")
    return tuple(mismatches)


def verify_metadata(
    requirements: Sequence[CollectionRequirement],
    collections: Mapping[str, Mapping[str, Any]],
    indexes: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> VerificationReport:
    """Inspect supplied metadata only. Missing snapshots fail closed.

    collections maps names to full listCollections records (type/options).
    indexes maps collection names to index_information results. Missing optional
    performance indexes are warnings; an unexpected uniqueness/TTL constraint
    is an error because it can prevent writes or destroy authoritative data.
    """
    findings = []

    def add(severity: str, code: str, position: int, index: int = -1) -> None:
        findings.append(Diagnostic(severity, code, position, index))

    for position, requirement in enumerate(requirements):
        if requirement.name not in collections:
            add("error", "missing_collection", position)
            continue
        collection = collections[requirement.name]
        if not isinstance(collection, Mapping) or not isinstance(collection.get("options", {}), Mapping):
            add("error", "invalid_collection_metadata", position)
            continue
        options = collection.get("options", {})
        if requirement.ordinary and (
            collection.get("type") != "collection" or options.get("capped", False) is not False
            or "timeseries" in options or "viewOn" in options
        ):
            add("error", "collection_shape", position)
        if requirement.simple_collation and not _equal(_collation(options.get("collation")), {"locale": "simple"}):
            add("error", "collection_collation", position)
        if requirement.forbid_ttl and "expireAfterSeconds" in options:
            add("error", "collection_ttl", position)
        actual = indexes.get(requirement.name)
        if not isinstance(actual, Mapping):
            add("error", "missing_index_metadata", position)
            continue
        expected = (IndexRequirement("_id_", (("_id", 1),), True, unique=True),) + requirement.indexes
        for index_position, index in enumerate(expected):
            severity = "error" if index.critical else "warning"
            if index.name not in actual:
                add(severity, "missing_index", position, index_position)
                continue
            for mismatch in compare_index(index, actual[index.name], options.get("collation")):
                # An added uniqueness/TTL constraint changes writes/data, even
                # when the original index existed only for query performance.
                level = "error" if mismatch in ("unique", "ttl") else severity
                add(level, mismatch, position, index_position)
        known = {item.name for item in expected}
        for name, metadata in actual.items():
            if not isinstance(metadata, Mapping):
                add("error", "invalid_index_metadata", position)
                continue
            if requirement.forbid_ttl and "expireAfterSeconds" in metadata:
                add("error", "forbidden_ttl", position)
            if name not in known:
                dangerous = requirement.forbid_extra_indexes or metadata.get("unique", False) is not False
                add("error" if dangerous else "warning", "unexpected_index", position)
    return VerificationReport(tuple(findings))
