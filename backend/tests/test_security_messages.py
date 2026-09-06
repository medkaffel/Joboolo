"""Current application relationships, fake collections only; no network or DB."""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from routes import messages as mod


def matches(doc, query):
    for key, value in query.items():
        if key == "$or":
            if not any(matches(doc, part) for part in value):
                return False
        elif isinstance(value, dict) and "$in" in value:
            if doc.get(key) not in value["$in"]:
                return False
        elif doc.get(key) != value:
            return False
    return True


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *args):
        return self

    async def to_list(self, length):
        return self.docs[:length]


class Collection:
    def __init__(self, docs):
        self.docs = docs
        self.writes = 0

    async def find_one(self, query):
        return next((d for d in self.docs if matches(d, query)), None)

    def find(self, query):
        return Cursor([d for d in self.docs if matches(d, query)])

    async def distinct(self, field, query):
        return list({d[field] for d in self.docs if matches(d, query)})

    async def count_documents(self, query):
        return sum(matches(d, query) for d in self.docs)

    async def insert_one(self, doc):
        self.writes += 1
        self.docs.append(doc)

    async def update_many(self, query, update):
        self.writes += 1
        for d in self.docs:
            if matches(d, query):
                d.update(update["$set"])


@pytest.fixture
def db(monkeypatch):
    db = SimpleNamespace(
        users=Collection([
            {"_id": "candidate", "user_type": "candidate", "is_active": True, "first_name": "Test"},
            {"_id": "employer", "user_type": "employer", "is_active": True, "first_name": "Example"},
        ]),
        jobs=Collection([{"_id": "job", "employer_id": "employer", "is_active": False}]),
        applications=Collection([{"job_id": "job", "candidate_id": "candidate", "status": "pending"}]),
        messages=Collection([{
            "_id": "message", "sender_id": "employer", "recipient_id": "candidate",
            "text": "Existing message", "created_at": datetime.now(timezone.utc), "read": False,
        }]),
    )
    monkeypatch.setattr(mod, "get_database", AsyncMock(return_value=db))
    return db


def user(role):
    return SimpleNamespace(id=role, user_type=role, is_active=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("role,other", [("candidate", "employer"), ("employer", "candidate")])
async def test_existing_application_allows_both_directions_even_after_job_closed(db, role, other):
    assert await mod._can_message(db, user(role), other)
    result = await mod.send_message(mod.SendMessage(recipient_id=other, text="Hello", job_id="job"), user(role))
    assert result["text"] == "Hello"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["application_removed", "job_removed", "job_transferred", "inactive", "role_changed"])
async def test_old_message_never_overrides_current_relationship(db, change):
    if change == "application_removed":
        db.applications.docs.clear()
    elif change == "job_removed":
        db.jobs.docs.clear()
    elif change == "job_transferred":
        db.jobs.docs[0]["employer_id"] = "another_employer"
    elif change == "inactive":
        db.users.docs[1]["is_active"] = False
    else:
        db.users.docs[1]["user_type"] = "partner"
    me = user("candidate")
    assert not await mod._can_message(db, me, "employer")
    with pytest.raises(mod.HTTPException) as exc:
        await mod.send_message(mod.SendMessage(recipient_id="employer", text="Hello"), me)
    assert exc.value.status_code == 403
    with pytest.raises(mod.HTTPException) as exc:
        await mod.thread("employer", me)
    assert exc.value.status_code == 403
    assert await mod.conversations(me) == []
    assert await mod.unread_count(me) == {"count": 0}
    assert db.messages.writes == 0


@pytest.mark.asyncio
async def test_arbitrary_user_identity_is_not_revealed(db):
    db.users.docs.append({"_id": "stranger", "user_type": "employer", "is_active": True})
    with pytest.raises(mod.HTTPException) as exc:
        await mod.thread("stranger", user("candidate"))
    assert exc.value.status_code == 403
    assert db.messages.writes == 0


@pytest.mark.asyncio
async def test_job_id_must_belong_to_the_same_application_relationship(db):
    db.jobs.docs.append({"_id": "unrelated", "employer_id": "employer"})
    with pytest.raises(mod.HTTPException) as exc:
        await mod.send_message(mod.SendMessage(recipient_id="candidate", text="Hello", job_id="unrelated"), user("employer"))
    assert exc.value.status_code == 403
    assert db.messages.writes == 0


@pytest.mark.asyncio
async def test_authorized_thread_and_counts_remain_available(db):
    me = user("candidate")
    assert await mod.unread_count(me) == {"count": 1}
    assert len(await mod.conversations(me)) == 1
    result = await mod.thread("employer", me)
    assert result["other"]["id"] == "employer"
    assert result["messages"][0]["text"] == "Existing message"
    assert await mod.unread_count(me) == {"count": 0}


@pytest.mark.asyncio
async def test_admin_has_no_global_messaging_bypass(db):
    assert not await mod._can_message(db, user("admin"), "candidate")


@pytest.mark.asyncio
async def test_self_contact_denied(db):
    assert not await mod._can_message(db, user("candidate"), "candidate")
