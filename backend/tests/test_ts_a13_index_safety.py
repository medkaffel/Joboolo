"""A13 G0: in-memory contracts only; migration sources are parsed, never run."""
import ast
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
import sys

import pytest

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
import mongo_index_safety as safety
from domains.talent_stream.index_requirements import TS_INDEX_REQUIREMENTS


IDENTITY = safety.IndexRequirement("identity", (("owner", 1), ("version", 1)), True, unique=True)


def metadata(requirement):
    result = {"key": list(requirement.keys), "unique": requirement.unique}
    for key, value in (("partialFilterExpression", requirement.partial_filter),
                       ("collation", requirement.collation),
                       ("expireAfterSeconds", requirement.expire_after_seconds)):
        if value is not None:
            result[key] = deepcopy(value)
    result.update(sparse=requirement.sparse, hidden=requirement.hidden)
    return result


def snapshots(requirements=TS_INDEX_REQUIREMENTS):
    collections = {c.name: {"type": "collection", "options": {}} for c in requirements}
    indexes = {c.name: {"_id_": {"key": [("_id", 1)]},
                       **{i.name: metadata(i) for i in c.indexes}} for c in requirements}
    return collections, indexes


def test_exact_and_ordered_keys():
    actual = metadata(IDENTITY)
    assert safety.compare_index(IDENTITY, actual) == ()
    actual["key"].reverse()
    assert safety.compare_index(IDENTITY, actual) == ("keys",)


@pytest.mark.parametrize("option,value,code", [
    ("key", [("owner", -1), ("version", 1)], "keys"),
    ("key", [("owner", True), ("version", 1)], "keys"),
    ("unique", False, "unique"), ("unique", 1, "unique"),
    ("sparse", True, "sparse"), ("hidden", True, "hidden"),
    ("partialFilterExpression", {"owner": {"$exists": True}}, "partial_filter"),
    ("partialFilterExpression", None, "partial_filter"),
    ("expireAfterSeconds", 0, "ttl"), ("expireAfterSeconds", None, "ttl"),
    ("collation", {"locale": "en", "strength": 2}, "collation"),
    ("wildcardProjection", {"private": 1}, "unexpected_options"),
])
def test_incompatible_options(option, value, code):
    actual = metadata(IDENTITY)
    actual[option] = value
    assert code in safety.compare_index(IDENTITY, actual)


def test_partial_filter_exact_structure():
    requirement = replace(IDENTITY, partial_filter={"owner": {"$type": "string"}})
    actual = metadata(requirement)
    assert safety.compare_index(requirement, actual) == ()
    actual["partialFilterExpression"] = {"owner": {"$exists": True}}
    assert safety.compare_index(requirement, actual) == ("partial_filter",)


def test_ttl_exact_value_and_type():
    requirement = replace(IDENTITY, expire_after_seconds=60)
    actual = metadata(requirement)
    assert safety.compare_index(requirement, actual) == ()
    actual["expireAfterSeconds"] = 61
    assert safety.compare_index(requirement, actual) == ("ttl",)


@pytest.mark.parametrize("explicit", [False, True])
def test_simple_collation_default(explicit):
    actual = metadata(IDENTITY)
    if explicit:
        actual["collation"] = {"locale": "simple"}
    assert safety.compare_index(IDENTITY, actual) == ()


def test_effective_non_simple_collation():
    default = {"locale": "en", "strength": 2}
    actual = metadata(IDENTITY)
    actual["collation"] = default
    assert safety.compare_index(IDENTITY, actual, default) == ()
    actual["collation"] = {"locale": "en", "strength": 3}
    assert safety.compare_index(IDENTITY, actual, default) == ("collation",)


def test_omitted_index_collation_is_simple_not_collection_inheritance():
    # index_information is persisted metadata, not create_index arguments:
    # a binary index has no collation field even on a non-simple collection.
    actual = metadata(IDENTITY)
    assert safety.compare_index(IDENTITY, actual, {"locale": "en", "strength": 2}) == ("collation",)


def test_explicit_simple_requirement_accepts_binary_index_on_non_simple_collection():
    requirement = replace(IDENTITY, collation={"locale": "simple"})
    actual = metadata(IDENTITY)  # persisted binary index: collation omitted
    assert safety.compare_index(requirement, actual, {"locale": "en", "strength": 2}) == ()


@pytest.mark.parametrize("unique", [None, True, False])
def test_native_identity_implicit_uniqueness(unique):
    requirement = safety.IndexRequirement("_id_", (("_id", 1),), True, unique=True)
    actual = {"key": [("_id", 1)]}
    if unique is not None:
        actual["unique"] = unique
    assert safety.compare_index(requirement, actual) == (("unique",) if unique is False else ())


@pytest.mark.parametrize("target", ["_id_", "identity"])
@pytest.mark.parametrize("missing", [True, False])
def test_missing_vs_incompatible_critical(target, missing):
    requirements = (safety.CollectionRequirement("sample", (IDENTITY,)),)
    collections, indexes = snapshots(requirements)
    if missing:
        del indexes["sample"][target]
    else:
        indexes["sample"][target]["key"] = [("wrong", 1)]
    report = safety.verify_metadata(requirements, collections, indexes)
    assert not report.ok
    assert report.diagnostics[0].code == ("missing_index" if missing else "keys")


def test_missing_performance_index_is_nonfatal():
    requirement = replace(IDENTITY, critical=False, unique=False)
    requirements = (safety.CollectionRequirement("sample", (requirement,)),)
    collections, indexes = snapshots(requirements)
    del indexes["sample"][requirement.name]
    report = safety.verify_metadata(requirements, collections, indexes)
    assert report.ok
    assert report.diagnostics == (safety.Diagnostic("warning", "missing_index", 0, 1),)


def test_empty_and_conforming_snapshots_remain_unchanged():
    empty = {}
    report = safety.verify_metadata(TS_INDEX_REQUIREMENTS, empty, empty)
    assert not report.ok and len(report.diagnostics) == 13
    assert empty == {}
    collections, indexes = snapshots()
    original = deepcopy((collections, indexes))
    first = safety.verify_metadata(TS_INDEX_REQUIREMENTS, collections, indexes)
    assert first.ok and first.diagnostics == ()
    assert safety.verify_metadata(TS_INDEX_REQUIREMENTS, collections, indexes) == first
    assert (collections, indexes) == original


@pytest.mark.parametrize("options", [
    {"capped": True}, {"timeseries": {"timeField": "at"}},
    {"viewOn": "other"}, {"collation": {"locale": "en"}}, {"expireAfterSeconds": 60},
])
def test_a11_collection_safety(options):
    requirements = (TS_INDEX_REQUIREMENTS[-1],)
    collections, indexes = snapshots(requirements)
    collections[requirements[0].name]["options"] = options
    assert not safety.verify_metadata(requirements, collections, indexes).ok


def test_redaction_and_extra_a11_index():
    requirements = (TS_INDEX_REQUIREMENTS[-1],)
    collections, indexes = snapshots(requirements)
    secret = "mongodb://fictional:secret@invalid.test/person@example.test"
    indexes[requirements[0].name][secret] = {
        "key": [(secret, 1)], "expireAfterSeconds": 60, "payload": {"email": secret},
    }
    report = safety.verify_metadata(requirements, collections, indexes)
    assert not report.ok
    rendered = json.dumps(asdict(report))
    assert all(token not in rendered for token in (secret, "mongodb", "secret", "email", "payload"))
    assert {d.code for d in report.diagnostics} == {"forbidden_ttl", "unexpected_index"}


def _literal(node, constants):
    if isinstance(node, ast.Name):
        return constants[node.id]
    if isinstance(node, ast.Subscript):
        return _literal(node.value, constants)[_literal(node.slice, constants)]
    return ast.literal_eval(node)


def test_manifest_matches_shipped_migration_declarations_without_importing_them():
    shipped = {}
    for path in sorted((BACKEND / "scripts").glob("migrate_ts_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        constants = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                try:
                    constants[node.targets[0].id] = ast.literal_eval(node.value)
                except (ValueError, TypeError):
                    pass
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "create_index":
                continue
            receiver = node.func.value
            collection = receiver.attr if isinstance(receiver, ast.Attribute) else {
                "grants": "talent_stream_grants", "events": "talent_stream_privacy_events",
            }[receiver.id]
            keys = _literal(node.args[0], constants)
            if isinstance(keys, str):
                keys = [(keys, 1)]
            options = {kw.arg: _literal(kw.value, constants) for kw in node.keywords}
            name = options.pop("name")
            assert (collection, name) not in shipped
            shipped[collection, name] = (tuple(keys), options)
    manifest = {}
    for collection in TS_INDEX_REQUIREMENTS:
        assert collection.ordinary and collection.forbid_ttl
        for index in collection.indexes:
            options = {}
            if index.unique:
                options["unique"] = True
            if index.partial_filter is not None:
                options["partialFilterExpression"] = index.partial_filter
            if index.collation is not None:
                options["collation"] = index.collation
            assert index.critical == index.unique
            assert not index.sparse and not index.hidden and index.expire_after_seconds is None
            assert (collection.name, index.name) not in manifest
            manifest[collection.name, index.name] = (index.keys, options)
    assert len(TS_INDEX_REQUIREMENTS) == 13 and len(manifest) == 32
    assert manifest == shipped
    assert ("recruiter_verifications", "ts_a8_recruiter_verification_state") in manifest


@pytest.mark.parametrize("relative", ["mongo_index_safety.py", "domains/talent_stream/index_requirements.py"])
def test_no_mongo_or_mutation_dependency(relative):
    tree = ast.parse((BACKEND / relative).read_text(encoding="utf-8"))
    allowed_imports = {"collections.abc", "dataclasses", "typing", "mongo_index_safety"}
    forbidden = {"create_index", "create_collection", "drop", "drop_index", "rename",
                 "insert_one", "insert_many", "update_one", "update_many", "delete_one",
                 "delete_many", "bulk_write", "replace_one", "command", "find", "aggregate",
                 "connect_to_mongo", "AsyncIOMotorClient", "MongoClient", "eval", "exec", "__import__"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module in allowed_imports
        if isinstance(node, ast.Import):
            assert all(alias.name in allowed_imports for alias in node.names)
        if isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            assert name not in forbidden
