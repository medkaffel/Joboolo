"""SSRF regression tests: synthetic DNS/HTTP, never contact any destination."""
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import feed_http as mod


@pytest.mark.parametrize("url", [
    "http://localhost/x", "http://localhost./x", "http://service.local/x",
    "http://service.internal/x", "http://service/x", "http://127.0.0.1/x",
    "http://127.1/x", "http://2130706433/x", "http://0x7f000001/x",
    "http://127\u30020.0.1/x", "http://\uff11\uff12\uff17.0.0.1/x",
    "http://10.0.0.1/x", "http://172.16.0.1/x", "http://192.168.1.1/x",
    "http://169.254.169.254/latest/meta-data", "http://100.100.100.200/x",
    "http://0.0.0.0/x", "http://224.0.0.1/x", "http://[::1]/x",
    "http://[fc00::1]/x", "http://[fe80::1%25eth0]/x",
    "http://[::ffff:127.0.0.1]/x", "http://[2002:7f00:1::]/x",
    "file:///etc/passwd", "ftp://example.com/x", "http://user:password@example.com/x",
    "http://example.com:8080/x", "http://example.com:bad/x", "http://example.com\\@127.0.0.1/x",
    "http://example.com/\r\nx", "", "//example.com/x",
])
def test_rejects_unsafe_url_before_any_io(url):
    with pytest.raises(mod.UnsafeFeedURL):
        mod.validate_feed_url(url)


@pytest.mark.parametrize("url", ["https://example.com/feed.xml", "http://example.com/feed.xml?key=fake", "https://8.8.8.8/feed.xml"])
def test_public_http_and_https_formats_preserved(url):
    assert mod.validate_feed_url(url) == url


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], ["8.8.8.8", "192.168.1.1"], []])
async def test_dns_rejects_any_non_public_answer(monkeypatch, addresses):
    underlying = SimpleNamespace(resolve=AsyncMock(return_value=[{"host": ip} for ip in addresses]), close=AsyncMock())
    monkeypatch.setattr(mod.aiohttp.resolver, "DefaultResolver", lambda: underlying)
    resolver = mod.PublicFeedResolver()
    with pytest.raises(mod.UnsafeFeedURL):
        await resolver.resolve("example.com", 443)
    await resolver.close()
    underlying.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_validated_dns_answers_are_returned_unchanged_and_rebinding_denied(monkeypatch):
    answers = [{"hostname": "example.com", "host": "8.8.8.8", "port": 443,
                "family": socket.AF_INET, "proto": 0, "flags": socket.AI_NUMERICHOST}]
    underlying = SimpleNamespace(resolve=AsyncMock(side_effect=[answers, [{"host": "127.0.0.1"}]]), close=AsyncMock())
    monkeypatch.setattr(mod.aiohttp.resolver, "DefaultResolver", lambda: underlying)
    resolver = mod.PublicFeedResolver()
    assert await resolver.resolve("example.com", 443) is answers
    with pytest.raises(mod.UnsafeFeedURL):
        await resolver.resolve("example.com", 443)
    await resolver.close()


class Response:
    def __init__(self, status=200, location=None, chunks=(b"<jobs/>",)):
        self.status = status
        self.headers = {"Location": location} if location is not None else {}
        self.charset = None
        self.chunks = chunks
        self.content = self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError("synthetic HTTP error")

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            yield chunk


def fake_http(monkeypatch, responses):
    calls, settings = [], {}
    resolver = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(mod, "PublicFeedResolver", lambda: resolver)

    def connector(**kwargs):
        settings["connector"] = kwargs
        return "fake-connector"

    monkeypatch.setattr(mod.aiohttp, "TCPConnector", connector)

    class Client:
        def __init__(self, **kwargs):
            settings["session"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def get(self, url, **kwargs):
            calls.append((url, kwargs))
            return responses.pop(0)

    monkeypatch.setattr(mod.aiohttp, "ClientSession", Client)
    return calls, settings, resolver


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["http://127.0.0.1/x", "//169.254.169.254/x", "file:///etc/passwd", "http://[::1]/x"])
async def test_private_redirect_is_never_requested(monkeypatch, target):
    calls, _, resolver = fake_http(monkeypatch, [Response(302, target)])
    with pytest.raises(mod.UnsafeFeedURL):
        await mod.fetch_feed_xml("https://example.com/feed")
    assert len(calls) == 1
    assert calls[0][1] == {"allow_redirects": False}
    resolver.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_public_relative_redirect_and_connector_safety_settings(monkeypatch):
    calls, settings, resolver = fake_http(monkeypatch, [Response(302, "/new.xml"), Response()])
    assert await mod.fetch_feed_xml("https://example.com/feed") == "<jobs/>"
    assert [url for url, _ in calls] == ["https://example.com/feed", "https://example.com/new.xml"]
    assert settings["connector"] == {"resolver": resolver, "use_dns_cache": False}
    assert settings["session"]["trust_env"] is False
    resolver.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_redirect_loop_is_bounded(monkeypatch):
    calls, _, _ = fake_http(monkeypatch, [Response(302, "/loop")] * 6)
    with pytest.raises(mod.UnsafeFeedURL):
        await mod.fetch_feed_xml("https://example.com/feed")
    assert len(calls) == 6


@pytest.mark.asyncio
async def test_decoded_response_size_is_bounded(monkeypatch):
    monkeypatch.setattr(mod, "MAX_FEED_BYTES", 5)
    fake_http(monkeypatch, [Response(chunks=(b"123", b"456"))])
    with pytest.raises(mod.UnsafeFeedURL):
        await mod.fetch_feed_xml("https://example.com/feed")


@pytest.mark.asyncio
async def test_import_uses_safe_fetch_before_any_job_write(monkeypatch):
    import partner_feed
    db = SimpleNamespace(partner_profiles=SimpleNamespace(find_one=AsyncMock(return_value={
        "xml_feed_url": "http://127.0.0.1/feed", "billing_mode": "per_click",
    })))
    fetch = AsyncMock(side_effect=mod.UnsafeFeedURL("Forbidden"))
    monkeypatch.setattr(partner_feed, "fetch_feed_xml", fetch)
    with pytest.raises(partner_feed.HTTPException) as exc:
        await partner_feed.import_feed(db, "fake-partner")
    assert exc.value.status_code == 400
    fetch.assert_awaited_once_with("http://127.0.0.1/feed")


@pytest.mark.asyncio
async def test_real_connector_uses_pinned_ip_and_preserves_tls_hostname(monkeypatch):
    answers = [{"hostname": "example.com", "host": "8.8.8.8", "port": 443,
                "family": socket.AF_INET, "proto": 0, "flags": socket.AI_NUMERICHOST}]
    dns = SimpleNamespace(resolve=AsyncMock(return_value=answers), close=AsyncMock())
    monkeypatch.setattr(mod.aiohttp.resolver, "DefaultResolver", lambda: dns)

    class StopBeforeNetwork(Exception):
        pass

    connect = AsyncMock(side_effect=StopBeforeNetwork)
    monkeypatch.setattr(mod.aiohttp.TCPConnector, "_wrap_create_connection", connect)
    with pytest.raises(StopBeforeNetwork):
        await mod.fetch_feed_xml("https://example.com/feed")
    dns.resolve.assert_awaited_once()
    assert connect.await_args.kwargs["addr_infos"][0][4] == ("8.8.8.8", 443)
    assert connect.await_args.kwargs["server_hostname"] == "example.com"


@pytest.mark.asyncio
async def test_real_connector_never_connects_to_private_dns_answer(monkeypatch):
    dns = SimpleNamespace(resolve=AsyncMock(return_value=[{"host": "127.0.0.1"}]), close=AsyncMock())
    monkeypatch.setattr(mod.aiohttp.resolver, "DefaultResolver", lambda: dns)
    connect = AsyncMock(side_effect=AssertionError("Network connection forbidden"))
    monkeypatch.setattr(mod.aiohttp.TCPConnector, "_wrap_create_connection", connect)
    with pytest.raises(mod.UnsafeFeedURL):
        await mod.fetch_feed_xml("https://example.com/feed")
    connect.assert_not_awaited()
