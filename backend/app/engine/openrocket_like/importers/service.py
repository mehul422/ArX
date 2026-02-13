from __future__ import annotations

import os

from app.engine.openrocket_like.importers.base import MotorImportResult
from app.engine.openrocket_like.importers.eng import import_eng
from app.engine.openrocket_like.importers.rse import import_rse
from app.engine.openrocket_like.models import MotorRecord
from app.engine.openrocket_like.propellant_registry import PropellantRegistry


class MotorImportService:
    def __init__(self, registry: PropellantRegistry | None = None) -> None:
        self.registry = registry or PropellantRegistry()

    def import_file(self, path: str) -> MotorImportResult:
        ext = os.path.splitext(path)[1].lower()
        if ext == ".eng":
            result = import_eng(path)
        elif ext == ".rse":
            result = import_rse(path)
        else:
            raise ValueError("unsupported motor file type")

        if result.record.propellant_label:
            self.registry.resolve(result.record.propellant_label)
        return result

    def merge_presets(self, presets: list[MotorRecord], imported: list[MotorRecord]) -> list[MotorRecord]:
        return [*presets, *imported]

