from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.engine.openrocket_like.models import MotorRecord


@dataclass(frozen=True)
class MotorImportResult:
    record: MotorRecord
    warnings: list[str]


class MotorImporter(Protocol):
    def import_file(self, path: str) -> MotorImportResult:
        ...

