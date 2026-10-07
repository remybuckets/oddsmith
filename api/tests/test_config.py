from app.config import Settings


def _settings(**overrides) -> Settings:
    base = {"database_url": "postgresql://x/y", "supabase_url": "http://sb.test/"}
    return Settings(_env_file=None, **(base | overrides))


def test_empty_token_budget_means_no_budget():
    assert _settings(daily_token_budget="").daily_token_budget is None


def test_token_budget_parses_integer():
    assert _settings(daily_token_budget="250000").daily_token_budget == 250_000


def test_supabase_urls_derive_from_base_url_without_double_slash():
    settings = _settings()
    assert settings.auth_issuer == "http://sb.test/auth/v1"
    assert settings.jwks_url == "http://sb.test/auth/v1/.well-known/jwks.json"


def test_limits_default_to_spec_values():
    settings = _settings()
    assert settings.daily_question_limit == 15
    assert settings.per_ip_requests_per_minute == 10
