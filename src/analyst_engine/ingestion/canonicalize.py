"""URL canonicalization and SSRF-safe host validation."""

from __future__ import annotations

import hashlib
import ipaddress
import socket
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

_ALLOWED_SCHEMES = frozenset({"http", "https"})
_DEFAULT_PORTS = {"http": 80, "https": 443}


class UrlValidationError(ValueError):
    """Base error for URL canonicalization and host validation failures."""


class UnsupportedSchemeError(UrlValidationError):
    """Raised when the URL scheme is not HTTP or HTTPS."""


class EmbeddedCredentialsError(UrlValidationError):
    """Raised when the URL contains embedded userinfo credentials."""


class InvalidHostError(UrlValidationError):
    """Raised when the host is missing, empty, or cannot be resolved."""


class PrivateNetworkError(UrlValidationError):
    """Raised when the host resolves to a private or otherwise restricted address."""


def _is_restricted_ip(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _validate_host_address(host: str, *, block_private_networks: bool) -> None:
    if not block_private_networks:
        return

    hostname = host.strip()
    if not hostname:
        raise InvalidHostError("URL host is missing or empty")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        if _is_restricted_ip(literal):
            raise PrivateNetworkError(f"host resolves to restricted address: {hostname}")
        return

    try:
        addr_infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise InvalidHostError(f"unable to resolve host: {hostname}") from exc

    if not addr_infos:
        raise InvalidHostError(f"unable to resolve host: {hostname}")

    for _family, _socktype, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        try:
            resolved = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise InvalidHostError(f"invalid resolved address for host: {hostname}") from exc
        if _is_restricted_ip(resolved):
            raise PrivateNetworkError(f"host resolves to restricted address: {hostname}")


def _build_netloc(hostname: str, port: int | None, scheme: str) -> str:
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return hostname
    return f"{hostname}:{port}"


def canonicalize_url(url: str, *, block_private_networks: bool) -> tuple[str, str]:
    """Return a canonical URL and its SHA-256 fingerprint hex digest."""
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise UnsupportedSchemeError(f"unsupported URL scheme: {parsed.scheme}")

    if parsed.username is not None or parsed.password is not None:
        raise EmbeddedCredentialsError("URL must not contain embedded credentials")

    hostname = parsed.hostname
    if hostname is None:
        raise InvalidHostError("URL host is missing or empty")

    hostname = hostname.lower()
    _validate_host_address(hostname, block_private_networks=block_private_networks)

    path = parsed.path or "/"
    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    sorted_query = urlencode(sorted(query_pairs, key=lambda pair: pair[0]))
    netloc = _build_netloc(hostname, parsed.port, scheme)

    canonical = urlunparse((scheme, netloc, path, "", sorted_query, ""))
    fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
    return canonical, fingerprint
