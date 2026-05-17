"""First-run ALSA device picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Label, ListItem, ListView, Static

from ..devices import AlsaDevice, BackendChoice, list_devices


_PULSE_LABEL = (
    "PulseAudio (shared)  —  routes through PipeWire/Pulse; lets other apps "
    "play at the same time, not bit-perfect"
)


class DevicePickerScreen(Screen):
    """Lets the user pick an audio output: PulseAudio (shared) or hw: ALSA."""

    BINDINGS = [
        ("enter", "select", "Select"),
        ("q", "app.quit", "Quit"),
    ]

    def __init__(
        self,
        current_backend: str = "",
        current_card_name: str = "",
        current_device_index: int = 0,
    ) -> None:
        super().__init__()
        self._devices: list[AlsaDevice] = list_devices()
        self._current_backend = current_backend
        self._current_card_name = current_card_name
        self._current_device_index = current_device_index

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                items = [ListItem(Label(_PULSE_LABEL))] + [
                    ListItem(Label(d.label)) for d in self._devices
                ]
                yield Vertical(
                    Label("[b]Choose an audio output[/]", id="title"),
                    Static(
                        "PulseAudio lets tide-pod share the device with other "
                        "apps. Pick a hw: device for exclusive bit-perfect "
                        "output (only tide-pod will get audio).",
                        id="hint",
                    ),
                    ListView(*items, id="devices"),
                    Static("Enter: select   Q: quit", id="footer-hint"),
                    id="picker-box",
                )

    def on_mount(self) -> None:
        lv = self.query_one("#devices", ListView)
        lv.focus()
        # If there's a currently-active output, highlight it. The first row
        # is the PulseAudio entry; ALSA devices start at index 1.
        if self._current_backend == "pulse":
            lv.index = 0
            return
        if self._current_backend == "alsa" and self._current_card_name:
            for i, d in enumerate(self._devices):
                if (
                    d.card_name == self._current_card_name
                    and d.device == self._current_device_index
                ):
                    lv.index = i + 1
                    return
        # No saved choice — default-highlight any obvious DAC by card name.
        for i, d in enumerate(self._devices):
            if any(t in d.card_name.lower() for t in ("schiit", "dac", "topping", "rme")):
                lv.index = i + 1
                break

    def _choice_at(self, index: int) -> BackendChoice | None:
        if index == 0:
            return BackendChoice(backend="pulse")
        alsa_idx = index - 1
        if 0 <= alsa_idx < len(self._devices):
            return BackendChoice(backend="alsa", alsa=self._devices[alsa_idx])
        return None

    def action_select(self) -> None:
        lv = self.query_one("#devices", ListView)
        if lv.index is None:
            return
        choice = self._choice_at(lv.index)
        if choice is not None:
            self.dismiss(choice)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is None:
            return
        choice = self._choice_at(event.list_view.index)
        if choice is not None:
            self.dismiss(choice)
