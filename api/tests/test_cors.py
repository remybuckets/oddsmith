async def test_preflight_from_web_app_is_allowed(client):
    response = await client.options(
        "/me",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_unknown_origin_gets_no_cors_headers(client):
    response = await client.get("/health", headers={"Origin": "https://evil.example"})

    assert "access-control-allow-origin" not in response.headers


def test_allowed_origins_come_from_comma_separated_env():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        database_url="x",
        supabase_url="y",
        cors_allowed_origins="https://oddsmith.app, http://localhost:3000",
    )
    assert settings.allowed_origins == ["https://oddsmith.app", "http://localhost:3000"]
