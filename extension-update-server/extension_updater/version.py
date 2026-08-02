from __future__ import annotations

import re
from dataclasses import dataclass
from functools import total_ordering

_VERSION_RE = re.compile(r"^(?:0|[1-9][0-9]{0,4})(?:\.(?:0|[1-9][0-9]{0,4})){0,3}$")


@total_ordering
@dataclass(frozen=True)
class ChromeVersion:
    """A Chrome extension version with component-wise comparison."""

    value: str
    parts: tuple[int, ...]

    @classmethod
    def parse(cls, value: str, *, allow_zero: bool = False) -> ChromeVersion:
        if not isinstance(value, str) or not _VERSION_RE.fullmatch(value):
            raise ValueError(f"invalid Chrome version: {value!r}")

        parts = tuple(int(part) for part in value.split("."))
        if any(part > 65535 for part in parts):
            raise ValueError(f"Chrome version component exceeds 65535: {value!r}")
        if not allow_zero and not any(parts):
            raise ValueError("Chrome version must not be all zero")
        return cls(value=value, parts=parts)

    @property
    def comparable(self) -> tuple[int, int, int, int]:
        return (*self.parts, *(0 for _ in range(4 - len(self.parts))))

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ChromeVersion):
            return NotImplemented
        return self.comparable < other.comparable

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ChromeVersion):
            return False
        return self.comparable == other.comparable

