"""Fetch a master plan image from a URL into a run's input folder.

Downloading server-side keeps browser CORS and hotlink rules out of the
picture and lets the normal upload pipeline run unchanged. Only public
http(s) hosts are allowed, the response must be an image, and the size is
capped before anything is written.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from pathlib import Path
from urllib.parse import urlparse

import httpx


class RemoteImageError(ValueError):
    """The URL could not be used as a master plan image."""


ALLOWED_SCHEMES = {"http", "https"}
CONTENT_TYPE_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
USER_AGENT = "GreenOpenAreaIntelligence/1.0 (+master-plan-analysis)"


def validate_image_url(url: str) -> str:
    """Return the URL if it is a public http(s) address; raise otherwise."""
    candidate = (url or "").strip()
    parsed = urlparse(candidate)
    if parsed.scheme not in ALLOWED_SCHEMES or not parsed.hostname:
        raise RemoteImageError("Image URL must start with http:// or https:// and include a host.")

    host = parsed.hostname
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except socket.gaierror as exc:
        raise RemoteImageError(f"Image URL host could not be resolved: {host}") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise RemoteImageError("Image URL must point to a public host.")
    return candidate


def download_image(url: str, destination_dir: Path, *, max_bytes: int, timeout: float = 25.0) -> Path:
    """Stream the image at ``url`` into ``destination_dir`` and return its path."""
    url = validate_image_url(url)
    destination_dir.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}) as client:
        with client.stream("GET", url) as response:
            if response.status_code != 200:
                raise RemoteImageError(f"Image URL returned HTTP {response.status_code}.")

            content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
            if not content_type.startswith("image/"):
                raise RemoteImageError(f"Image URL did not return an image (content-type {content_type or 'unknown'}).")

            declared = response.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                raise RemoteImageError(f"Image is larger than the {max_bytes // (1024 * 1024)} MB limit.")

            file_name = _file_name_for(url, content_type)
            destination = destination_dir / file_name
            written = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes():
                    written += len(chunk)
                    if written > max_bytes:
                        handle.close()
                        destination.unlink(missing_ok=True)
                        raise RemoteImageError(f"Image is larger than the {max_bytes // (1024 * 1024)} MB limit.")
                    handle.write(chunk)

    if written == 0:
        destination.unlink(missing_ok=True)
        raise RemoteImageError("Image URL returned an empty body.")
    return destination


def _file_name_for(url: str, content_type: str) -> str:
    raw = Path(urlparse(url).path).name or "master_plan"
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(raw).stem).strip("._") or "master_plan"
    suffix = Path(raw).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        suffix = CONTENT_TYPE_EXTENSIONS.get(content_type, ".jpg")
    return f"{stem[:80]}{suffix}"
