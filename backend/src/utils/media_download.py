"""Public-media URL checks and bounded direct downloads with pinned addresses."""
import http.client
import ipaddress
from pathlib import Path
import socket
import ssl
from urllib.parse import urljoin, urlsplit

MAX_MEDIA_BYTES = 512 * 1024 * 1024
PLATFORM_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be", "vimeo.com", "www.vimeo.com", "player.vimeo.com"}


def validate_media_url(url: str):
    if not isinstance(url, str) or len(url) > 4096 or any(ord(c) < 32 for c in url):
        raise ValueError("Invalid media URL")
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Use a public HTTP or HTTPS media URL without credentials.")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if port != (443 if parsed.scheme == "https" else 80):
        raise ValueError("Media links must use the standard HTTP or HTTPS port.")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
    except ValueError:
        literal = None
    if literal is not None and not literal.is_global:
        raise ValueError("Local and private-network media URLs are not allowed.")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)}
    except OSError as exc:
        raise ValueError("The media host could not be resolved.") from exc
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Local and private-network media URLs are not allowed.")
    return parsed, sorted(addresses)


def download_direct_media(url: str, destination: str) -> Path:
    """Every redirect is revalidated; the connection uses the validated IP."""
    for _ in range(6):
        parsed, addresses = validate_media_url(url)
        port = 443 if parsed.scheme == "https" else 80
        connection = http.client.HTTPConnection(parsed.hostname, port, timeout=60)
        # Pin the validated address while preserving Host and TLS server name.
        sock = socket.create_connection((addresses[0], port), timeout=60)
        if parsed.scheme == "https":
            sock = ssl.create_default_context().wrap_socket(sock, server_hostname=parsed.hostname)
        connection.sock = sock
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            connection.request("GET", path, headers={"User-Agent": "Mudaris/1.0", "Accept": "audio/*,video/*,application/octet-stream"})
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise ValueError("The media redirect has no destination.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("The media link could not be downloaded.")
            content_type = response.getheader("Content-Type", "").split(";", 1)[0].lower()
            if not (content_type.startswith(("audio/", "video/")) or content_type == "application/octet-stream"):
                raise ValueError("Direct links must point to an audio or video file.")
            length = response.getheader("Content-Length")
            if length and int(length) > MAX_MEDIA_BYTES:
                raise ValueError("This media file exceeds the 512 MB limit.")
            target = Path(destination)
            size = 0
            try:
                with target.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > MAX_MEDIA_BYTES:
                            raise ValueError("This media file exceeds the 512 MB limit.")
                        output.write(chunk)
                if not size:
                    raise ValueError("The media file is empty.")
                return target
            except Exception:
                target.unlink(missing_ok=True)
                raise
        finally:
            connection.close()
    raise ValueError("The media link redirected too many times.")
