"""First-run ALSA device picker."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Center, Middle, Vertical
from textual.screen import Screen
from textual.widgets import Label, ListItem, ListView, Static

from ..devices import AlsaDevice, list_devices


class DevicePickerScreen(Screen):
    """Lets the user pick a `hw:CARD,DEV` ALSA device for bit-perfect output."""

    BINDINGS = [
        ("enter", "select", "Select"),
        ("q", "app.quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._devices: list[AlsaDevice] = list_devices()

    def compose(self) -> ComposeResult:
        with Middle():
            with Center():
                yield Vertical(
                    Label("[b]Choose an ALSA output device[/]", id="title"),
                    Static(
                        "Pick a hw: device for bit-perfect output. The default "
                        "ALSA device routes through PulseAudio/PipeWire and is "
                        "not bit-perfect.",
                        id="hint",
                    ),
                    ListView(
                        *[ListItem(Label(d.label)) for d in self._devices],
                        id="devices",
                    ),
                    Static("Enter: select   Q: quit", id="footer-hint"),
                    id="picker-box",
                )

    def on_mount(self) -> None:
        lv = self.query_one("#devices", ListView)
        if self._devices:
            lv.focus()
            # Default-highlight any obvious DAC by checking the card name.
            for i, d in enumerate(self._devices):
                if any(t in d.card_name.lower() for t in ("schiit", "dac", "topping", "rme")):
                    lv.index = i
                    break

    def action_select(self) -> None:
        lv = self.query_one("#devices", ListView)
        if lv.index is None or not self._devices:
            return
        chosen = self._devices[lv.index]
        self.dismiss(chosen.address)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.index is None or not self._devices:
            return
        chosen = self._devices[event.list_view.index]
        self.dismiss(chosen.address)
