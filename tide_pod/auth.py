"""Tidal authentication via PKCE.

PKCE is the only Tidal auth flow that returns a token entitled to
Hi-Res Lossless and Lossless FLAC streams — the legacy device-flow OAuth
client is capped at HIGH (AAC 320k). tidalapi documents this in
`login_pkce`. So we use PKCE here:

    1. Build a login URL with `session.pkce_login_url()`.
    2. User opens it in a browser, logs in.
    3. Tidal redirects to an 'Oops' page; the user copies that URL back.
    4. `session.pkce_get_auth_token(redirect_url)` → token JSON.
    5. `session.process_auth_token(json, is_pkce_token=True)` activates it.
    6. We persist via `save_session_to_file`. `is_pkce` is stored in the
       file so future runs restore the PKCE-flavored client_id and keep
       hi-res entitlements.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Union

import tidalapi
from tidalapi.media import Quality

from .config import Config, secure_session_file, session_path

logger = logging.getLogger(__name__)


QUALITY_MAP = {
    "low_96k": Quality.low_96k,
    "low_320k": Quality.low_320k,
    "high_lossless": Quality.high_lossless,
    "hi_res_lossless": Quality.hi_res_lossless,
}


@dataclass
class PkceLogin:
    url: str  # full login URL the user opens in a browser


def new_session(config: Config) -> tidalapi.Session:
    """Create a tidalapi.Session pre-configured with the chosen quality."""
    cfg = tidalapi.Config(quality=QUALITY_MAP.get(config.quality, Quality.hi_res_lossless))
    return tidalapi.Session(cfg)


def try_resume(session: tidalapi.Session) -> bool:
    """Load a previously saved session from disk. Returns True if logged in."""
    path = session_path()
    if not path.exists():
        return False
    try:
        session.load_session_from_file(path)
    except Exception:
        logger.exception("Failed to load saved session")
        return False
    try:
        return bool(session.check_login())
    except Exception:
        logger.exception("check_login() raised")
        return False


def start_pkce_login(session: tidalapi.Session) -> PkceLogin:
    """Build the PKCE login URL for the user to open in a browser."""
    return PkceLogin(url=session.pkce_login_url())


def complete_pkce_login(session: tidalapi.Session, redirect_url: str) -> None:
    """Exchange the redirect URL (with ?code=...) for tokens and activate."""
    token_json: Dict[str, Union[str, int]] = session.pkce_get_auth_token(redirect_url)
    session.process_auth_token(token_json, is_pkce_token=True)


def finalize_login(session: tidalapi.Session) -> None:
    """Persist the freshly-logged-in session to disk."""
    session.save_session_to_file(session_path())
    secure_session_file()


def logout() -> None:
    """Remove the on-disk session."""
    path = session_path()
    if path.exists():
        path.unlink()
