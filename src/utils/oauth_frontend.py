"""
OAuth frontend return-origin helpers.

When the Hub frontend (localhost or production) talks to a shared API, OAuth
providers / API callbacks must send the browser back to the origin that started
the flow — not a hardcoded FRONTEND_URL.

We encode an allowlisted origin into the OAuth `state` (backward compatible):
  raw_state|fe=<urlsafe_b64(origin)>
"""
from __future__ import annotations

import base64
import logging
from typing import Optional, Tuple
from urllib.parse import quote

from fastapi.responses import RedirectResponse

from ..config import settings

logger = logging.getLogger(__name__)

_FE_MARKER = "|fe="


def _default_frontend() -> str:
    return (settings.FRONTEND_URL or "http://localhost:3000").rstrip("/")


def allowed_frontend_origins() -> set[str]:
    origins = {o.rstrip("/") for o in (settings.ALLOWED_ORIGINS or []) if o}
    origins.add(_default_frontend())
    return origins


def sanitize_frontend_origin(origin: Optional[str]) -> str:
    """Return an allowlisted origin, else the configured FRONTEND_URL."""
    if not origin:
        return _default_frontend()
    cleaned = origin.strip().rstrip("/")
    if cleaned in allowed_frontend_origins():
        return cleaned
    # Accept http://127.0.0.1:PORT when localhost:PORT is allowlisted
    if cleaned.startswith("http://127.0.0.1:"):
        as_localhost = "http://localhost:" + cleaned.split(":", 2)[-1]
        if as_localhost in allowed_frontend_origins():
            return as_localhost
    logger.warning("Rejected OAuth frontend_origin=%s; using default", cleaned)
    return _default_frontend()


def with_frontend_origin(state: str, frontend_origin: Optional[str] = None) -> str:
    """Append allowlisted frontend origin to OAuth state when provided by the client."""
    if not frontend_origin:
        return state
    base = sanitize_frontend_origin(frontend_origin)
    token = base64.urlsafe_b64encode(base.encode("utf-8")).decode("ascii").rstrip("=")
    raw, _ = split_oauth_state(state)
    return f"{raw}{_FE_MARKER}{token}"


def split_oauth_state(state: Optional[str]) -> Tuple[Optional[str], str]:
    """
    Split provider state into (raw_state, frontend_base).

    raw_state is what routers already parse (e.g. user_<uuid>).
    """
    default = _default_frontend()
    if not state:
        return None, default
    if _FE_MARKER not in state:
        return state, default
    raw, token = state.rsplit(_FE_MARKER, 1)
    try:
        pad = "=" * (-len(token) % 4)
        origin = base64.urlsafe_b64decode(token + pad).decode("utf-8")
        return raw or None, sanitize_frontend_origin(origin)
    except Exception:
        logger.warning("Failed to decode frontend origin from OAuth state")
        return state, default


def frontend_connections_path(frontend_origin: Optional[str] = None, path: str = "/connections") -> str:
    """Absolute frontend URL used as OAuth redirect_uri for browser-return providers."""
    if not path.startswith("/"):
        path = "/" + path
    return f"{sanitize_frontend_origin(frontend_origin)}{path}"


def connections_redirect(
    state: Optional[str],
    *,
    success: Optional[str] = None,
    error: Optional[str] = None,
    detail: Optional[str] = None,
    extra_query: Optional[str] = None,
) -> RedirectResponse:
    """Redirect browser to /connections on the origin that started OAuth."""
    _, base = split_oauth_state(state)
    parts = []
    if success:
        parts.append(f"success={quote(str(success), safe='')}")
    if error:
        parts.append(f"error={quote(str(error), safe='')}")
    if detail:
        parts.append(f"detail={quote(str(detail), safe='')}")
    if extra_query:
        parts.append(extra_query.lstrip("?&"))
    query = "&".join(parts)
    url = f"{base}/connections" + (f"?{query}" if query else "")
    return RedirectResponse(url=url)
