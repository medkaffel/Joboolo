"""Bounded XML feed downloads; public destinations only, including DNS/redirects.

The connector uses the validated resolver answers directly. A separate DNS
preflight followed by a normal HTTP request would allow DNS rebinding.
"""
import ipaddress
import re
import socket
from urllib.parse import urljoin

import aiohttp
from yarl import URL

MAX_FEED_BYTES = 20 * 1024 * 1024
MAX_REDIRECTS = 5


class UnsafeFeedURL(ValueError):
    pass


def _public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    if not address.is_global or address.is_multicast or address.is_reserved:
        return False
    if isinstance(address, ipaddress.IPv6Address):
        # Reject IPv4 transition/tunnel forms and scoped addresses.
        if (address not in ipaddress.ip_network("2000::/3") or address.scope_id
                or address.ipv4_mapped or address.sixtofour or address.teredo):
            return False
    return True


def validate_feed_url(url: str) -> str:
    if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise UnsafeFeedURL("URL de flux invalide")
    try:
        # Use the HTTP client's own IDNA/URL normalization BEFORE checking IPs.
        # Unicode dots/digits can otherwise become a private IP inside the client,
        # whose connector skips DNS resolution for literal IP addresses.
        parts = URL(url)
        host = (parts.raw_host or "").rstrip(".").lower()
        port = parts.port
    except ValueError as exc:
        raise UnsafeFeedURL("URL de flux invalide") from exc
    if (parts.scheme not in ("http", "https") or not host
            or parts.raw_user is not None or parts.raw_password is not None
            or port not in (None, 80, 443) or "%" in host):
        raise UnsafeFeedURL("Seuls les flux HTTP(S) publics sur les ports 80/443 sont autorisés")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        if ("." not in host or re.fullmatch(r"[0-9.]+", host)
                or host.endswith((".localhost", ".local", ".internal", ".home", ".lan"))):
            raise UnsafeFeedURL("Adresse de flux interne interdite")
    else:
        if not _public_ip(host):
            raise UnsafeFeedURL("Adresse de flux non publique interdite")
    return str(parts)


class PublicFeedResolver(aiohttp.abc.AbstractResolver):
    def __init__(self):
        self._resolver = aiohttp.resolver.DefaultResolver()

    async def resolve(self, host, port=0, family=socket.AF_INET):
        answers = await self._resolver.resolve(host, port, family)
        if not answers or any(not _public_ip(answer["host"]) for answer in answers):
            raise UnsafeFeedURL("Le DNS du flux pointe vers une adresse non publique")
        return answers

    async def close(self):
        await self._resolver.close()


async def fetch_feed_xml(url: str) -> str:
    current = validate_feed_url(url)
    resolver = PublicFeedResolver()
    connector = aiohttp.TCPConnector(resolver=resolver, use_dns_cache=False)
    try:
        async with aiohttp.ClientSession(
            connector=connector, trust_env=False,
            timeout=aiohttp.ClientTimeout(total=30),
            cookie_jar=aiohttp.DummyCookieJar(),
        ) as client:
            for hop in range(MAX_REDIRECTS + 1):
                async with client.get(current, allow_redirects=False) as response:
                    if response.status in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location")
                        if not location or hop == MAX_REDIRECTS:
                            raise UnsafeFeedURL("Redirections de flux invalides ou trop nombreuses")
                        current = validate_feed_url(urljoin(current, location))
                        continue
                    response.raise_for_status()
                    data = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        data.extend(chunk)
                        if len(data) > MAX_FEED_BYTES:
                            raise UnsafeFeedURL("Flux XML trop volumineux (maximum 20 Mo)")
                    return data.decode(response.charset or "utf-8-sig")
    finally:
        await resolver.close()
