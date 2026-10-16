"""What identifies a shade or gateway - serial numbers, Bluetooth names - kept out of the log."""

from __future__ import annotations

import logging

from powerview_connect import Home


class Redactions(logging.Filter):
    """A log filter that replaces each text it was given with a name for it."""

    def __init__(self) -> None:
        """A filter with nothing to replace yet."""
        super().__init__()
        self._names: dict[str, str] = {}

    def add(self, text: str | None, name: str) -> None:
        """Replace `text` with `name` from now on; an empty text is ignored."""
        if text:
            self._names[text] = name

    def add_home(self, home: Home) -> None:
        """Replace each serial number and Bluetooth name in `home`."""
        for gateway in home.gateways:
            self.add(gateway.serial, f"<serial of {gateway.name}>")
        for shade in home.shades.values():
            self.add(shade.serial, f"<serial of shade {shade.id}>")
            self.add(shade.ble_name, f"<shade {shade.id}>")

    def redact(self, text: str) -> str:
        """`text` with everything given replaced, the longest first."""
        for secret in sorted(self._names, key=len, reverse=True):
            text = text.replace(secret, self._names[secret])
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        """Replace what was given in the record's message; every record passes."""
        record.msg, record.args = self.redact(record.getMessage()), None
        return True


REDACTIONS = Redactions()
"""The replacements of every entry, for the hub's logger."""
