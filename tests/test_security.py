import pytest

from bot.security import validate_url_shape


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/file.pdf",
    "http://10.0.0.5/file.pdf",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://localhost/admin",
    "http://router.local/",
    "file:///etc/passwd",
    "https://user:pass@example.com/file.pdf",
])
def test_rejects_private_or_invalid_urls(url):
    with pytest.raises(ValueError):
        validate_url_shape(url)


@pytest.mark.parametrize("url", [
    "https://example.com/files/a.pdf",
    "http://cdn.example.org/video.mp4?token=abc",
])
def test_accepts_public_http_shapes(url):
    assert validate_url_shape(url) == url


def test_redirect_to_private_ip_is_rejected(monkeypatch):
    from bot import security

    class Response:
        status_code = 302
        headers = {"Location": "http://127.0.0.1/admin"}

        def close(self):
            pass

    class Session:
        def __init__(self):
            self.calls = []

        def request(self, method, url, **kwargs):
            self.calls.append(url)
            return Response()

    monkeypatch.setattr(security, "_assert_public_dns", lambda _: None)
    session = Session()
    with pytest.raises(ValueError):
        security.safe_request("https://example.com/start", session=session)
    assert session.calls == ["https://example.com/start"]


def test_rejects_hostname_resolving_to_private_ip(monkeypatch):
    import socket
    from bot import security

    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.4", 443))
    ])
    with pytest.raises(ValueError, match="private or reserved"):
        security._assert_public_dns("https://example.com/")
