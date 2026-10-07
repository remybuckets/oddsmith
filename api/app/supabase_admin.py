"""Supabase Auth admin API, used only to delete a user (the database cascades the rest)."""

import uuid

import httpx

ADMIN_TIMEOUT_SECONDS = 10.0


class SupabaseAdmin:
    def __init__(self, supabase_url: str, service_role_key: str, http: httpx.AsyncClient) -> None:
        self._base_url = supabase_url.rstrip("/")
        self._headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
        }
        self._http = http

    async def delete_user(self, user_id: uuid.UUID) -> None:
        response = await self._http.delete(
            f"{self._base_url}/auth/v1/admin/users/{user_id}",
            headers=self._headers,
            timeout=ADMIN_TIMEOUT_SECONDS,
        )
        if response.status_code == httpx.codes.NOT_FOUND:
            return  # already gone
        response.raise_for_status()
