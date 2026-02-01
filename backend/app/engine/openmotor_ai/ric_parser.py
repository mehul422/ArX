from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


class _IgnoreTagsLoader(yaml.SafeLoader):
    pass


def _ignore_unknown_tag(loader: yaml.Loader, tag_suffix: str, node: yaml.Node):
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_scalar(node)


_IgnoreTagsLoader.add_multi_constructor("", _ignore_unknown_tag)


@dataclass(frozen=True)
class RicData:
    config: dict[str, Any]
    grains: list[dict[str, Any]]
    nozzle: dict[str, Any]
    propellant: dict[str, Any]


def load_ric(path: str) -> RicData:
    with open(path, "r", encoding="utf-8") as handle:
        payload = yaml.load(handle, Loader=_IgnoreTagsLoader)

    if not isinstance(payload, dict):
        raise ValueError("Invalid .ric payload")

    data = payload.get("data", {})
    config = data.get("config", {})
    grains = data.get("grains", [])
    nozzle = data.get("nozzle", {})
    propellant = data.get("propellant", {})

    if not isinstance(config, dict):
        raise ValueError("Invalid .ric config")
    if not isinstance(grains, list):
        raise ValueError("Invalid .ric grains")
    if not isinstance(nozzle, dict):
        raise ValueError("Invalid .ric nozzle")
    if not isinstance(propellant, dict):
        raise ValueError("Invalid .ric propellant")

    return RicData(config=config, grains=grains, nozzle=nozzle, propellant=propellant)
