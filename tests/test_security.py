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
