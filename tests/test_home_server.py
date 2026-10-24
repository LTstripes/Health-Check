"""Synthetic protected UI regressions; no real credentials, trust store or LAN bind."""

from __future__ import annotations

import asyncio
import json
import zipfile
from datetime import UTC, datetime, timedelta
from ipaddress import IPv4Address

import httpx
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from pydantic import ValidationError

from healthcheck import cli
from healthcheck.config import Settings
from healthcheck.db.engine import migrate_database
from healthcheck.profile_backup import create_backup, restore_profile
from healthcheck.runtime import prepare_runtime
from healthcheck.web import home_auth
from healthcheck.web.home_auth import COOKIE, HomeAuth, HomeServerError
from healthcheck.web.ingest_app import create_ingest_app
from healthcheck.web.ui_app import create_ui_app

PASSWORD = "synthetic owner passphrase 526"
ORIGIN = "https://127.0.0.1:8120"


@pytest.fixture(scope="session")
def security_material(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-access")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-test-only")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1)).not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([
            x509.IPAddress(IPv4Address("127.0.0.1")),
            x509.IPAddress(IPv4Address("192.168.3.43")),
        ]), critical=False).sign(key, hashes.SHA256())
    )
    certfile, keyfile = root / "cert.pem", root / "key.pem"
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                        serialization.PrivateFormat.PKCS8,
                                        serialization.NoEncryption()))
    return certfile, keyfile, home_auth.password_record(PASSWORD)


@pytest.fixture
def home(tmp_path, security_material):
    cert, key, record = security_material
    access = tmp_path / "access" / "password.json"
    access.parent.mkdir()
    access.write_text(json.dumps(record), encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "profile", ui_mode="home-server",
                        ui_auth_file=access, ui_tls_certfile=cert, ui_tls_keyfile=key)
    paths = prepare_runtime(settings)
    migrate_database(paths)
    app, _ = create_ui_app(settings)
    return app, settings, paths


def client_for(app):
    return TestClient(app, base_url=ORIGIN, follow_redirects=False)


def login(client, password=PASSWORD):
    return client.post("/login", data={"password": password}, headers={"Origin": ORIGIN})


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "8.8.8.8", "localhost", "127.0.0.2",
                                 "169.254.1.1", "100.64.0.1", "192.0.2.1", "224.0.0.1"])
def test_rejects_public_wildcard_and_special_ui_bind(host):
    with pytest.raises(ValidationError):
        Settings(ui_mode="home-server", ui_host=host)
    with pytest.raises(ValidationError):
        Settings(ui_host="192.168.3.43")


@pytest.mark.parametrize("host", ["127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.3.43"])
def test_allows_only_explicit_home_bind(host):
    assert Settings(ui_mode="home-server", ui_host=host).ui_host == host


def test_missing_access_or_tls_fails_before_runtime_creation(tmp_path, security_material):
    profile = tmp_path / "absent"
    with pytest.raises(HomeServerError, match="tls_unavailable"):
        create_ui_app(Settings(data_dir=profile, ui_mode="home-server"))
    cert, key, _ = security_material
    with pytest.raises(HomeServerError, match="password_unavailable"):
        create_ui_app(Settings(data_dir=profile, ui_mode="home-server",
                               ui_tls_certfile=cert, ui_tls_keyfile=key,
                               ui_auth_file=tmp_path / "missing.json"))
    assert not profile.exists()


def test_wrong_certificate_ip_and_invalid_verifier_fail_closed(home):
    _, settings, _ = home
    with pytest.raises(HomeServerError, match="wrong_ip"):
        create_ui_app(settings.model_copy(update={"ui_host": "192.168.1.8"}))
    settings.ui_auth_file.write_text('{"password":"raw-password-is-never-valid"}')
    with pytest.raises(HomeServerError, match="password_unavailable"):
        create_ui_app(settings)


def test_existing_profile_required_even_with_valid_access(home, tmp_path):
    _, settings, _ = home
    absent = tmp_path / "absent-profile"
    with pytest.raises(HomeServerError, match="requires_existing_profile"):
        create_ui_app(settings.model_copy(update={"data_dir": absent}))
    assert not absent.exists()


def test_standard_https_port_uses_browser_canonical_authority(home):
    _, settings, _ = home
    app, _ = create_ui_app(settings.model_copy(update={"ui_port": 443}))
    with TestClient(app, base_url="https://127.0.0.1", follow_redirects=False) as client:
        assert client.get("/login").status_code == 200
        assert client.post("/login", data={"password": PASSWORD},
                           headers={"Origin": "https://127.0.0.1"}).status_code == 303


@pytest.mark.parametrize("method,path", [
    ("GET", "/weight"), ("GET", "/brief"), ("GET", "/api/weight/series"),
    ("GET", "/api/analysis-export/sources"), ("POST", "/api/analysis-export"),
    ("POST", "/context"), ("GET", "/labs/anything/original"),
    ("GET", "/static/dashboard.css"), ("GET", "/missing"), ("GET", "/login/extra"),
    ("GET", "/healthz/extra"), ("POST", "/api/ingest/openscale"),
])
def test_anonymous_cannot_reach_any_personal_route(home, method, path):
    app, _, _ = home
    with client_for(app) as client:
        response = client.request(method, path, headers={"Origin": ORIGIN})
        assert response.status_code in {303, 401}
        if response.status_code == 303:
            assert response.headers["location"] == "/login"
        assert response.headers["cache-control"] == "no-store"
        assert "synthetic owner" not in response.text


def test_login_cookie_rotation_logout_and_private_routes(home):
    app, _, _ = home
    with client_for(app) as client:
        public = client.get("/login")
        assert public.status_code == 200 and 'type="password"' in public.text
        assert public.headers["x-frame-options"] == "DENY"
        assert public.headers["referrer-policy"] == "no-referrer"
        assert client.get("/healthz").json() == {"status": "ok", "service": "home-server-ui"}
        response = login(client)
        assert response.status_code == 303 and response.headers["location"] == "/brief"
        cookie = response.headers["set-cookie"]
        assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie
        assert "Path=/" in cookie and "Domain=" not in cookie
        first = client.cookies.get(COOKIE)
        assert app.state.home_auth.session(first)
        assert client.get("/api/weight/series").status_code == 200
        assert 'action="/logout"' in client.get("/weight").text
        assert client.get("/api/analysis-export/sources").status_code == 200
        assert client.get("/missing").status_code == 404
        assert login(client).status_code == 303
        assert first != client.cookies.get(COOKIE)
        assert not app.state.home_auth.session(first)
        second = client.cookies.get(COOKIE)
        assert client.get("/logout").status_code == 405
        assert client.post("/logout", headers={"Origin": ORIGIN}).status_code == 303
        assert not app.state.home_auth.session(second)
        assert client.get("/api/weight/series").status_code == 401


@pytest.mark.parametrize("path", ["/login", "/logout", "/context", "/api/analysis-export"])
@pytest.mark.parametrize("headers", [
    {}, {"Origin": "http://127.0.0.1:8120"}, {"Origin": "https://evil.example"},
    {"Origin": ORIGIN + "/"}, {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"},
    {"Origin": ORIGIN, "Referer": "https://evil.example/form"},
    {"Origin": "https://127.0.0.1:8121"}, {"Origin": "null"},
])
def test_all_mutations_including_login_logout_require_same_origin(home, path, headers):
    app, _, _ = home
    with client_for(app) as client:
        assert client.post(path, headers=headers, data={"password": PASSWORD}).status_code == 403


def test_duplicate_headers_bad_host_and_proxy_spoof_are_rejected(home):
    app, _, _ = home
    with client_for(app) as client:
        for headers in [
            [("Host", "127.0.0.1:8120"), ("Host", "127.0.0.1:8120")],
            [("Host", "192.168.3.43:8120")], [("Host", "evil@127.0.0.1:8120")],
            [("Cookie", "a=1"), ("Cookie", "a=2")],
            [("Cookie", f"{COOKIE}=a; {COOKIE}=b")],
        ]:
            assert client.get("/healthz", headers=headers).status_code == 403
        duplicate = [("Origin", ORIGIN), ("Origin", ORIGIN)]
        assert client.post("/login", headers=duplicate).status_code == 403
        assert client.request("TRACE", "/healthz").status_code == 405
        assert client.get("/login?password=never-in-url").status_code == 400
    with TestClient(app, base_url="http://127.0.0.1:8120") as client:
        assert client.get("/healthz", headers={"X-Forwarded-Proto": "https",
                                              "Forwarded": "proto=https"}).status_code == 403


def test_idle_absolute_expiry_restart_and_session_store_bound(home, monkeypatch):
    app, settings, _ = home
    now = [100.0]
    monkeypatch.setattr(home_auth.time, "monotonic", lambda: now[0])
    auth = app.state.home_auth
    token = auth.issue()
    now[0] += home_auth.IDLE_SECONDS
    assert not auth.session(token)
    token = auth.issue()
    for _ in range(home_auth.ABSOLUTE_SECONDS // 600):
        now[0] += 600
        active = auth.session(token)
    assert not active
    token = auth.issue()
    assert not HomeAuth.configure(settings).session(token)
    for _ in range(home_auth.MAX_SESSIONS + 2):
        auth.issue()
    assert len(auth.sessions) == home_auth.MAX_SESSIONS
    assert not auth.session(token)


def test_password_rotation_fails_closed_until_restart(home):
    app, settings, _ = home
    with client_for(app) as client:
        assert login(client).status_code == 303
        settings.ui_auth_file.write_text("{}")
        response = client.get("/weight")
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert not app.state.home_auth.sessions


def test_failed_login_throttling_body_bounds_and_no_secret_output(home, capsys):
    app, _, _ = home
    with client_for(app) as client:
        assert login(client, "wrong synthetic password").status_code == 401
        assert not client.cookies
        assert client.post("/login", content=b"x" * 4097,
                           headers={"Origin": ORIGIN,
                                    "Content-Type": "application/x-www-form-urlencoded"}
                           ).status_code == 413
        assert client.post("/login", content=b"password=a&password=b",
                           headers={"Origin": ORIGIN,
                                    "Content-Type": "application/x-www-form-urlencoded"}
                           ).status_code == 400
        login(client, "wrong synthetic password")
        login(client, "wrong synthetic password")
        response = login(client)
        assert response.status_code == 429 and response.headers["retry-after"] == "60"
        assert PASSWORD not in response.text
    assert PASSWORD not in capsys.readouterr().out


def test_authenticated_mutation_reaches_existing_handler_and_error_is_no_store(home):
    app, _, _ = home

    @app.get("/synthetic-error")
    async def synthetic_error():
        raise RuntimeError("do not expose secret")

    with client_for(app) as client:
        login(client)
        invalid = client.post("/api/analysis-export", json={}, headers={"Origin": ORIGIN})
        assert invalid.status_code == 422  # Existing route validates, auth does not reject.
        assert invalid.headers["cache-control"] == "no-store"
        error = client.get("/synthetic-error")
        assert error.status_code == 500
        assert "secret" not in error.text and error.headers["cache-control"] == "no-store"


def test_verifier_must_be_external_and_backup_restores_without_access(home, tmp_path):
    _, settings, paths = home
    with pytest.raises(HomeServerError, match="outside_code_and_profile"):
        home_auth.write_password(paths.root / "password.json", settings, PASSWORD)
    archive = tmp_path / "profile.zip"
    create_backup(paths.root, archive)
    with zipfile.ZipFile(archive) as handle:
        assert not any("password" in name or "access" in name for name in handle.namelist())
    restored = tmp_path / "restored"
    restore_profile(archive, restored)
    assert (restored / "healthcheck.db").is_file()
    assert not (restored / "password.json").exists()


def test_cli_home_preflight_never_prepares_or_listens_on_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "prepare_runtime", lambda _: pytest.fail("must not prepare"))
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **k: pytest.fail("must not listen"))
    assert cli.main(["serve", "--ui-mode", "home-server", "--data-dir",
                     str(tmp_path / "missing")]) == 2
    assert "tls_unavailable" in capsys.readouterr().err


def test_cli_direct_tls_options_and_ingest_contract_unchanged(home, monkeypatch):
    _, settings, _ = home
    calls = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda *a, **kw: calls.append(kw))
    args = ["serve", "--data-dir", str(settings.data_dir), "--ui-mode", "home-server",
            "--auth-file", str(settings.ui_auth_file), "--tls-certfile",
            str(settings.ui_tls_certfile), "--tls-keyfile", str(settings.ui_tls_keyfile)]
    assert cli.main(args) == 0
    assert calls[-1]["proxy_headers"] is False and calls[-1]["access_log"] is False
    assert calls[-1]["host"] == "127.0.0.1" and calls[-1]["ssl_keyfile"]
    app, _ = create_ingest_app(settings)
    with TestClient(app) as client:
        assert client.get("/healthz").json()["service"] == "ingest"
        assert client.get("/login").status_code == 404
        assert client.get("/weight").status_code == 404


def test_cli_password_is_local_interactive_only(home, monkeypatch, capsys):
    _, settings, _ = home
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: pytest.fail("must not prompt"))
    assert cli.main(["ui-password", "--data-dir", str(settings.data_dir),
                     "--auth-file", str(settings.ui_auth_file)]) == 2
    assert "interactive local terminal" in capsys.readouterr().err


def test_local_password_setup_reset_and_environment_do_not_leak(home, tmp_path,
                                                              monkeypatch, capsys):
    _, settings, _ = home
    target = tmp_path / "new-access" / "password.json"
    monkeypatch.setenv("HEALTHCHECK_UI_MODE", "home-server")
    monkeypatch.setenv("HEALTHCHECK_UI_HOST", "192.168.3.43")
    monkeypatch.setattr(cli.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(cli.getpass, "getpass", lambda _: PASSWORD)
    args = ["ui-password", "--data-dir", str(settings.data_dir), "--auth-file", str(target)]
    assert cli.main(args) == 0
    saved = target.read_bytes()
    salt, digest = home_auth.read_password(target)
    assert HomeAuth(target, salt, digest).verify(PASSWORD)
    assert PASSWORD.encode() not in saved
    assert cli.main(args) == 2  # Exclusive creation cannot overwrite access.
    assert target.read_bytes() == saved
    assert cli.main([*args, "--replace"]) == 0
    assert target.read_bytes() != saved
    output = capsys.readouterr()
    assert PASSWORD not in output.out + output.err


def test_login_slow_body_is_bounded(home, monkeypatch):
    app, _, _ = home
    monkeypatch.setattr(home_auth, "LOGIN_READ_SECONDS", 0.01)

    async def check():
        async def body():
            yield b"password="
            await asyncio.sleep(1)
            yield b"never-reached"

        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                     base_url=ORIGIN) as client:
            response = await client.post("/login", content=body(), headers={
                "Origin": ORIGIN, "Content-Type": "application/x-www-form-urlencoded",
            })
            assert response.status_code == 408
            assert response.headers["cache-control"] == "no-store"

    asyncio.run(check())
