"""Supabase client (service-role key; the frontend never talks to Postgres directly)."""

import logging
from functools import lru_cache

import httpx
from supabase import Client, ClientOptions, create_client

from .config import get_settings

log = logging.getLogger("huda")


class _RetryingClient(httpx.Client):
    """Retry once when Supabase drops the connection before answering.

    One client is shared by API requests and the background pipeline. Over HTTP/2
    (supabase-py's default) a dropped connection fails every in-flight call with
    "Server disconnected"; HTTP/1.1 gives each thread its own pooled connection.
    """

    def send(self, request, **kwargs):
        try:
            return super().send(request, **kwargs)
        except httpx.RemoteProtocolError as exc:
            log.warning("supabase connection dropped (%s); retrying %s %s",
                        exc, request.method, request.url.path)
            return super().send(request, **kwargs)


@lru_cache
def sb() -> Client:
    s = get_settings()
    if not s.supabase_url or not s.supabase_service_role_key:
        raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")
    http = _RetryingClient(http2=False, timeout=httpx.Timeout(30.0), follow_redirects=True)
    return create_client(s.supabase_url, s.supabase_service_role_key,
                         options=ClientOptions(httpx_client=http))


def public_storage_url(bucket: str, path: str) -> str:
    return f"{get_settings().supabase_url}/storage/v1/object/public/{bucket}/{path}"
