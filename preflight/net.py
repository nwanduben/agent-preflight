"""Address rules for outbound calls.

Hosted, this app calls URLs that whoever is using it supplies. Without a check, that
turns the server into a way of reaching private networks and cloud metadata services,
so in public mode a URL must be https and must resolve only to public addresses.
"""
from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

BLOCKED_HOSTS = {"metadata.google.internal", "metadata.goog", "instance-data"}


def check_url(url: str, *, public_only: bool) -> str:
    """Empty string when the URL may be called; otherwise the reason it may not."""
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        return f"{u.scheme or 'missing'} is not an http(s) URL"
    host = u.hostname
    if not host:
        return "URL has no host"
    if not public_only:
        return ""
    if u.scheme != "https":
        return "only https URLs are allowed here"
    if host.lower() in BLOCKED_HOSTS:
        return f"{host} is a cloud metadata address"
    try:
        infos = socket.getaddrinfo(host, u.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as e:
        return f"{host} does not resolve ({e.strerror or e})"
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global or ip.is_multicast:
            return f"{host} resolves to {ip}, which is not a public address"
    return ""
