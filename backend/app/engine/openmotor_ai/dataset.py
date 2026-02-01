from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.engine.openmotor_ai.eng_parser import EngData, load_eng
from app.engine.openmotor_ai.ric_parser import RicData, load_ric


@dataclass(frozen=True)
class ReferencePair:
    ric_path: Path
    eng_path: Path
    ric: RicData
    eng: EngData


def load_reference_pairs(ric_dir: str, eng_dir: str, count: int = 10) -> list[ReferencePair]:
    ric_base = Path(ric_dir)
    eng_base = Path(eng_dir)
    pairs: list[ReferencePair] = []
    for idx in range(1, count + 1):
        ric_path = ric_base / f"{idx}.ric"
        eng_path = eng_base / f"{idx}.eng"
        if not ric_path.exists():
            raise FileNotFoundError(f"Missing .ric file: {ric_path}")
        if not eng_path.exists():
            raise FileNotFoundError(f"Missing .eng file: {eng_path}")
        pairs.append(
            ReferencePair(
                ric_path=ric_path,
                eng_path=eng_path,
                ric=load_ric(str(ric_path)),
                eng=load_eng(str(eng_path)),
            )
        )
    return pairs
