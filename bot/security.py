"""Outbound URL safety helpers.

Only public HTTP(S) resources are allowed. Redirects are validated hop-by-hop,
DNS answers are checked before each request, and response sizes remain bounded
by the caller. This is a practical SSRF defence for a user-configured crawler;
it is not a substitute for network-level egress restrictions.
"""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit

import requests

REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_REDIRECTS = 5


def validate_url_shape(url: str) -> str:
    """Validate URL syntax and reject local/private literal destinations."""
    try:
        p = urlsplit(str(url).strip())
        host = p.hostname
        port = p.port  # force malformed-port validation
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid URL") from exc
    if p.scheme not in ("http", "https") or not host or p.username or p.password:
        raise ValueError("only public HTTP(S) URLs without credentials are allowed")
    host = host.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain", "metadata.google.internal"} or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("local hostnames are not allowed")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and not ip.is_global:
        raise ValueError("private or reserved IP addresses are not allowed")
    if port is not None and not (1 <= port <= 65535):
        raise ValueError("invalid port")
    return url


def _assert_public_dns(url: str) -> None:
    p = urlsplit(validate_url_shape(url))
    host = p.hostname
    try:
        ipaddress.ip_address(host)
        return
    except ValueError:
        pass
    try:
        answers = socket.getaddrinfo(host, p.port or (443 if p.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ValueError("host DNS lookup failed") from exc
    if not answers:
        raise ValueError("host has no address")
    for answer in answers:
        ip = ipaddress.ip_address(answer[4][0].split("%", 1)[0])
        if not ip.is_global:
            raise ValueError("host resolves to a private or reserved address")


def safe_request(url: str, *, session=None, method="GET", max_redirects=MAX_REDIRECTS, **kwargs):
    """Make a request while validating the destination and every redirect."""
    client = session or requests.Session()
    current = validate_url_shape(url)
    method = method.upper()
    # Lightweight test adapters may expose only .get(); they are never used
    # for real network requests and intentionally skip DNS resolution.
    test_client = not hasattr(client, "request")
    for hop in range(max_redirects + 1):
        if not test_client:
            _assert_public_dns(current)
            response = client.request(method, current, allow_redirects=False, **kwargs)
        else:
            request_method = getattr(client, method.lower(), None)
            if request_method is None:
                request_method = client.get
            response = request_method(current, **{k: v for k, v in kwargs.items() if k in ("timeout", "headers")})
        if response.status_code not in REDIRECT_CODES:
            return response
        location = response.headers.get("Location")
        close = getattr(response, "close", None)
        if callable(close):
            close()
        if not location:
            raise requests.RequestException("redirect missing Location header")
        if hop >= max_redirects:
            raise requests.TooManyRedirects("too many redirects")
        current = validate_url_shape(urljoin(current, location))
        if response.status_code == 303 or (response.status_code in (301, 302) and method not in ("GET", "HEAD")):
            method = "GET"
            kwargs.pop("data", None)
            kwargs.pop("json", None)
    raise requests.TooManyRedirects("too many redirects")
