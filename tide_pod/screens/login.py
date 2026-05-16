"""Tidal PKCE login screen.

The user opens the URL we display, signs in with their browser, and is
redirected to a tidal.com 'Oops' page. They copy that URL and paste it
back here. We submit it to tidalapi for the code-for-token exchange.

PKCE is the only flow that returns a token authorized to stream Lossless
and Hi-Res Lossless — the legacy device-flow OAuth client tops out at
HIGH (AAC 320k).
"""

from __future__ import annotations

import logging

import tidalapi

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, Label, Static

from .. import auth

logger = logging.getLogger(__name__)


class LoginScreen(Screen):
    """PKCE login: open URL in browser, paste 'Oops' redirect URL back."""

    BINDINGS = [("q", "app.quit", "Quit"), ("escape", "cancel", "Cancel")]

    def __init__(self, session: tidalapi.Session) -> None:
        super().__init__()
        self.session = session

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                yield Vertical(
                    Label("[b]tide-pod[/]", id="title"),
                    Static("Sign in to Tidal (PKCE — required for lossless / hi-res)", id="subtitle"),
                    Static("", id="status"),
                    Label("", id="url"),
                    Static(
                        "Open the link above, sign in, and copy the URL of the\n"
                        "'Oops' page you get redirected to. Paste it below and\n"
                        "press Enter.",
                        id="hint",
                    ),
                    Input(placeholder="Paste redirect URL here…", id="redirect-input"),
                    Static("", id="error"),
                    Button("Cancel", id="cancel", variant="error"),
                    id="login-box",
                )

    def on_mount(self) -> None:
        self.query_one("#status", Static).update("Requesting login URL …")
        self.run_worker(self._fetch_url, thread=True, exclusive=True)

    def _fetch_url(self) -> None:
        try:
            login = auth.start_pkce_login(self.session)
        except Exception as exc:
            logger.exception("PKCE URL generation failed")
            self.app.call_from_thread(self._show_error, f"Couldn't start login: {exc}")
            return
        self.app.call_from_thread(self._show_url, login.url)

    def _show_url(self, url: str) -> None:
        self.query_one("#status", Static).update("Open this URL in your browser:")
        self.query_one("#url", Label).update(f'[link="{url}"]{url}[/]')
        self.query_one("#redirect-input", Input).focus()

    def _show_error(self, msg: str) -> None:
        self.query_one("#error", Static).update(f"[red]{msg}[/]")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "redirect-input":
            return
        url = event.value.strip()
        if not url:
            return
        self.query_one("#error", Static).update("")
        self.query_one("#status", Static).update("Exchanging code for token …")
        self.run_worker(lambda u=url: self._submit_redirect(u), thread=True, exclusive=True)

    def _submit_redirect(self, redirect_url: str) -> None:
        try:
            auth.complete_pkce_login(self.session, redirect_url)
            auth.finalize_login(self.session)
        except Exception as exc:
            logger.exception("PKCE token exchange failed")
            self.app.call_from_thread(self._show_error, f"Login failed: {exc}")
            return
        self.app.call_from_thread(self.dismiss, True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "cancel":
            self.dismiss(False)

    def action_cancel(self) -> None:
        self.dismiss(False)
