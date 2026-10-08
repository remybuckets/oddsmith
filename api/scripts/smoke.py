"""Post-deploy smoke test: one throwaway user through the whole API, then deleted.

    API_URL=https://<api>.up.railway.app SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \
    SUPABASE_ANON_KEY=... uv run python scripts/smoke.py

Uses one of the user's daily questions; the user and all their rows are deleted at the end.
Exits non-zero on the first check that fails.
"""

import os
import secrets
import sys

import httpx

TIMEOUT_SECONDS = 30


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"missing env var {name}")
    return value


def _check(label: str, response: httpx.Response, status: int, code: str | None = None) -> None:
    body = response.json() if "json" in response.headers.get("content-type", "") else {}
    actual_code = (body.get("error") or {}).get("code")
    ok = response.status_code == status and (code is None or actual_code == code)
    print(f"{'PASS' if ok else 'FAIL'}  {label}: {response.status_code} {actual_code or ''}")
    if not ok:
        sys.exit(f"unexpected response: {response.text[:300]}")


def _create_user(supabase: str, service_key: str, anon_key: str) -> tuple[str, str]:
    email = f"smoke-{secrets.token_hex(4)}@example.test"
    password = secrets.token_urlsafe(24)
    admin = {"apikey": service_key, "Authorization": f"Bearer {service_key}"}
    created = httpx.post(
        f"{supabase}/auth/v1/admin/users",
        headers=admin,
        timeout=TIMEOUT_SECONDS,
        json={"email": email, "password": password, "email_confirm": True},
    )
    created.raise_for_status()
    token = httpx.post(
        f"{supabase}/auth/v1/token?grant_type=password",
        headers={"apikey": anon_key},
        timeout=TIMEOUT_SECONDS,
        json={"email": email, "password": password},
    )
    token.raise_for_status()
    return created.json()["id"], token.json()["access_token"]


def main() -> None:
    supabase = _env("SUPABASE_URL").rstrip("/")
    api = httpx.Client(base_url=_env("API_URL").rstrip("/"), timeout=TIMEOUT_SECONDS)
    user_id, token = _create_user(
        supabase, _env("SUPABASE_SERVICE_ROLE_KEY"), _env("SUPABASE_ANON_KEY")
    )
    auth = {"Authorization": f"Bearer {token}"}
    print(f"throwaway user {user_id}")

    _check("GET /health", api.get("/health"), 200)
    _check("GET /me without token", api.get("/me"), 401, "unauthenticated")
    _check("GET /me", api.get("/me", headers=auth), 200)
    conversation = api.post("/conversations", headers=auth)
    _check("POST /conversations", conversation, 201)
    url = f"/conversations/{conversation.json()['data']['id']}/messages"
    question = {"content": "Who's injured for the next Arsenal game?"}
    _check("ask before 18+", api.post(url, headers=auth, json=question), 403, "age_not_confirmed")
    _check(
        "POST /onboarding/age",
        api.post("/onboarding/age", headers=auth, json={"is_over_18": True, "accepts_terms": True}),
        200,
    )

    answer = api.post(url, headers=auth, json=question)
    events = [line[7:] for line in answer.text.splitlines() if line.startswith("event: ")]
    print(f"{'PASS' if events[-1:] == ['message_end'] else 'FAIL'}  SSE answer: {events}")
    if events[-1:] != ["message_end"]:
        sys.exit("answer did not complete")

    _check("GET messages", api.get(url, headers=auth), 200)
    _check("DELETE /me", api.delete("/me", headers=auth), 200)
    _check("token after delete", api.get("/me", headers=auth), 401, "unauthenticated")
    print("smoke test passed")


if __name__ == "__main__":
    main()
