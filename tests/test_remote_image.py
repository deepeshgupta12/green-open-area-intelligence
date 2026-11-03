from pathlib import Path

import pytest

from app.utils.remote_image import RemoteImageError, _file_name_for, download_image, validate_image_url


def test_validate_image_url_rejects_non_http_and_private_hosts():
    with pytest.raises(RemoteImageError):
        validate_image_url("ftp://example.com/plan.jpg")
    with pytest.raises(RemoteImageError):
        validate_image_url("not a url")
    with pytest.raises(RemoteImageError):
        validate_image_url("http://127.0.0.1/plan.jpg")
    with pytest.raises(RemoteImageError):
        validate_image_url("http://localhost:2345/plan.jpg")


def test_file_name_is_derived_safely():
    assert _file_name_for("https://cdn.example.com/a/b/sattva-lumina-plan.jpg?x=1", "image/jpeg") == "sattva-lumina-plan.jpg"
    assert _file_name_for("https://cdn.example.com/plan", "image/png") == "plan.png"
    assert _file_name_for("https://cdn.example.com/", "image/webp") == "master_plan.webp"
    assert _file_name_for("https://cdn.example.com/../weird name!.JPEG", "image/jpeg") == "weird_name.jpeg"


def test_download_image_enforces_image_type_and_size(monkeypatch, tmp_path):
    import httpx

    monkeypatch.setattr("app.utils.remote_image.validate_image_url", lambda url: url)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/plan.jpg":
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"\xff\xd8" + b"x" * 500)
        if request.url.path == "/page.html":
            return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>")
        if request.url.path == "/big.jpg":
            return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"x" * 5000)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def client_factory(**kwargs):
        kwargs.pop("transport", None)
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr("app.utils.remote_image.httpx.Client", client_factory)

    saved = download_image("https://example.com/plan.jpg", tmp_path, max_bytes=10_000)
    assert saved == Path(tmp_path / "plan.jpg")
    assert saved.stat().st_size == 502

    with pytest.raises(RemoteImageError, match="did not return an image"):
        download_image("https://example.com/page.html", tmp_path, max_bytes=10_000)

    with pytest.raises(RemoteImageError, match="larger than"):
        download_image("https://example.com/big.jpg", tmp_path, max_bytes=1_000)
    assert not (tmp_path / "big.jpg").exists()

    with pytest.raises(RemoteImageError, match="HTTP 404"):
        download_image("https://example.com/missing.jpg", tmp_path, max_bytes=10_000)
