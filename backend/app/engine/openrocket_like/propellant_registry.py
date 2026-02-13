from __future__ import annotations

from dataclasses import dataclass

from app.engine.openrocket_like.models import PropellantFamily, PropellantLabel


@dataclass
class PropellantRegistry:
    _labels: dict[str, PropellantLabel]

    def __init__(self) -> None:
        self._labels = {}

    def register(self, label: str, *, family: PropellantFamily | None = None, source: str = "user") -> PropellantLabel:
        key = label.strip()
        if not key:
            raise ValueError("propellant label is required")
        entry = PropellantLabel(
            name=key,
            family=family or PropellantFamily.UNKNOWN,
            source=source,
        )
        self._labels[key.lower()] = entry
        return entry

    def resolve(self, label: str) -> PropellantLabel:
        key = label.strip().lower()
        if not key:
            raise ValueError("propellant label is required")
        if key in self._labels:
            return self._labels[key]
        return self.register(label, family=PropellantFamily.UNKNOWN, source="imported")

    def list_all(self) -> list[PropellantLabel]:
        return list(self._labels.values())

