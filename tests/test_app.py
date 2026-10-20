import sqlite3

import pytest

import app as app_module


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Give every test its own empty temporary database."""
    monkeypatch.setattr(app_module, "DATABASE", str(tmp_path / "test.db"))
    app_module.init_db()
    app_module.app.config["TESTING"] = True
    with app_module.app.test_client() as test_client:
        yield test_client


def create_link(client, **extra):
    payload = {"url": "https://www.google.com", **extra}
    return client.post("/api/shorten", json=payload)


def test_home_page_loads(client):
    assert client.get("/").status_code == 200


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_shorten_valid_url(client):
    response = create_link(client)
    data = response.get_json()
    assert response.status_code == 201
    assert len(data["short_code"]) == 6
    assert data["original_url"] == "https://www.google.com"
    assert data["short_url"].endswith(data["short_code"])


@pytest.mark.parametrize("bad_url", ["hello", "ftp://example.com", "javascript:alert(1)", ""])
def test_shorten_rejects_invalid_url(client, bad_url):
    response = client.post("/api/shorten", json={"url": bad_url})
    assert response.status_code == 400
    assert "error" in response.get_json()


def test_redirect_works(client):
    code = create_link(client).get_json()["short_code"]
    response = client.get(f"/{code}")
    assert response.status_code == 302
    assert response.headers["Location"] == "https://www.google.com"


def test_unknown_code_returns_404(client):
    assert client.get("/doesnotexist").status_code == 404


def test_custom_code_and_duplicate_rejected(client):
    first = create_link(client, custom_code="myportfolio")
    assert first.status_code == 201
    assert first.get_json()["short_code"] == "myportfolio"

    second = create_link(client, custom_code="myportfolio")
    assert second.status_code == 409


@pytest.mark.parametrize("bad_code", ["ab", "has space", "bad!chars", "api", "health"])
def test_invalid_custom_code_rejected(client, bad_code):
    assert create_link(client, custom_code=bad_code).status_code == 400


@pytest.mark.parametrize("bad_days", ["abc", "500", "-5"])
def test_invalid_expiry_rejected(client, bad_days):
    assert create_link(client, expires_in_days=bad_days).status_code == 400


def test_expired_link_returns_410(client):
    code = create_link(client, expires_in_days="1").get_json()["short_code"]

    with sqlite3.connect(app_module.DATABASE) as conn:
        conn.execute(
            "UPDATE urls SET expires_at = '2000-01-01 00:00:00' WHERE short_code = ?",
            (code,),
        )

    assert client.get(f"/{code}").status_code == 410
    assert client.get(f"/api/stats/{code}").get_json()["expired"] is True


def test_stats_track_clicks_and_last_visit(client):
    code = create_link(client).get_json()["short_code"]
    client.get(f"/{code}")
    client.get(f"/{code}")

    stats = client.get(f"/api/stats/{code}").get_json()
    assert stats["clicks"] == 2
    assert stats["last_visited"] is not None


def test_qr_code_is_a_png_image(client):
    code = create_link(client).get_json()["short_code"]
    response = client.get(f"/api/qr/{code}")
    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.data.startswith(b"\x89PNG")


def test_recent_links_lists_newest_first(client):
    create_link(client, custom_code="first-link")
    create_link(client, custom_code="second-link")

    links = client.get("/api/links").get_json()
    assert links[0]["short_code"] == "second-link"
    assert links[1]["short_code"] == "first-link"