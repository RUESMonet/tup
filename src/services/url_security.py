import ipaddress
import socket
from collections.abc import Callable, Iterable
from typing import TypeVar
from urllib.parse import urlparse


ExceptionT = TypeVar("ExceptionT", bound=Exception)
PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


def safe_https_base_url(
    base_url: str,
    allowed_hosts: Iterable[str],
    *,
    error_type: type[ExceptionT] = RuntimeError,
    error_message: str = "base URL is not allowed",
    proxy_fake_ip_allowed_hosts: Iterable[str] = (),
) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname:
        raise error_type(error_message)
    hostname = parsed.hostname.lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise error_type(error_message)
    normalized_allowed_hosts = {host.strip().lower() for host in allowed_hosts if host and host.strip()}
    if hostname not in normalized_allowed_hosts:
        raise error_type(error_message)
    fake_ip_allowed_hosts = {host.strip().lower() for host in proxy_fake_ip_allowed_hosts if host and host.strip()}
    try:
        ip = ipaddress.ip_address(hostname)
    except ValueError:
        _ensure_public_dns(hostname, error_type, error_message, allow_proxy_fake_ip=hostname in fake_ip_allowed_hosts)
        return normalized
    if _is_disallowed_ip(ip):
        raise error_type(error_message)
    return normalized


def hosts_from_urls(urls: Iterable[str | None]) -> set[str]:
    hosts: set[str] = set()
    for url in urls:
        if not url:
            continue
        host = urlparse(url).hostname
        if host:
            hosts.add(host.lower())
    return hosts


def hosts_from_csv(value: str | None) -> set[str]:
    if not value:
        return set()
    return {host.strip().lower() for host in value.split(",") if host.strip()}


def _ensure_public_dns(hostname: str, error_type: Callable[[str], ExceptionT], error_message: str, *, allow_proxy_fake_ip: bool) -> None:
    try:
        addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise error_type(error_message) from exc
    if not addresses:
        raise error_type(error_message)
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if allow_proxy_fake_ip and ip in PROXY_FAKE_IP_NETWORK:
            continue
        if _is_disallowed_ip(ip):
            raise error_type(error_message)


def _is_disallowed_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return not ip.is_global
