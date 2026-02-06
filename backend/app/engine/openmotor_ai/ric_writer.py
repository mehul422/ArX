from __future__ import annotations

from app.engine.openmotor_ai.spec import MotorSpec
from app.engine.openmotor_ai.ric_parser import _IgnoreTagsLoader
import re
import yaml


def _format_number(value: float) -> str:
    abs_value = abs(value)
    if abs_value >= 1000:
        text = f"{value:.1f}"
    elif abs_value >= 1:
        text = f"{value:.6f}"
    else:
        text = f"{value:.8f}"
    stripped = text.rstrip("0").rstrip(".")
    if stripped in ("", "-", "+"):
        return "0.0"
    if "." not in stripped and "e" not in stripped.lower():
        return f"{stripped}.0"
    return stripped


def _format_half_inches(value_m: float) -> float:
    inches = value_m / 0.0254
    rounded_in = round(inches * 2.0) / 2.0
    rounded_m = rounded_in * 0.0254
    return float(_format_number(rounded_m))


def _format_half_unit(value: float) -> float:
    rounded = round(value * 2.0) / 2.0
    if abs(rounded - int(rounded)) < 1e-9:
        return float(int(rounded))
    return float(_format_number(rounded))


class _FloatDumper(yaml.SafeDumper):
    pass


def _represent_float(dumper: yaml.SafeDumper, value: float):
    text = _format_number(value)
    return dumper.represent_scalar("tag:yaml.org,2002:float", text)


_FloatDumper.add_representer(float, _represent_float)


_NUMERIC_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\d*\.\d+)(?:[eE][+-]?\d+)?$")


def _coerce_numeric_strings(value):
    if isinstance(value, dict):
        return {k: _coerce_numeric_strings(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_coerce_numeric_strings(v) for v in value]
    if isinstance(value, str) and _NUMERIC_RE.match(value.strip()):
        try:
            return float(value)
        except Exception:
            return value
    return value


def normalize_ric_text(raw: str) -> str:
    payload = yaml.load(raw, Loader=_IgnoreTagsLoader)
    if not isinstance(payload, dict):
        return raw
    payload = _coerce_numeric_strings(payload)
    payload.pop("type", None)
    payload.pop("version", None)
    body = yaml.dump(
        payload,
        Dumper=_FloatDumper,
        default_flow_style=False,
        sort_keys=False,
    )
    return body.rstrip() + "\n" + _ric_footer()


def _ric_footer() -> str:
    return (
        "type: !!python/object/apply:uilib.fileIO.fileTypes\n"
        "- 3\n"
        "version: !!python/tuple\n"
        "- 0\n"
        "- 5\n"
        "- 0\n"
    )


def build_ric(spec: MotorSpec) -> str:
    payload = {
        "data": {
            "config": {
                "ambPressure": float(_format_number(spec.config.amb_pressure_pa)),
                "burnoutThrustThres": float(_format_number(spec.config.burnout_thrust_threshold_n)),
                "burnoutWebThres": float(_format_number(spec.config.burnout_web_threshold_m)),
                "mapDim": int(spec.config.map_dim),
                "maxMassFlux": float(_format_number(spec.config.max_mass_flux_kg_m2_s)),
                "maxPressure": float(_format_number(spec.config.max_pressure_pa)),
                "minPortThroat": float(_format_number(spec.config.min_port_throat_ratio)),
                "timestep": float(_format_number(spec.config.timestep_s)),
            },
            "grains": [
                {
                    "properties": {
                        "coreDiameter": _format_half_inches(grain.core_diameter_m),
                        "diameter": _format_half_inches(grain.diameter_m),
                        "inhibitedEnds": grain.inhibited_ends,
                        "length": _format_half_inches(grain.length_m),
                    },
                    "type": "BATES",
                }
                for grain in spec.grains
            ],
            "nozzle": {
                "convAngle": _format_half_unit(spec.nozzle.conv_angle_deg),
                "divAngle": _format_half_unit(spec.nozzle.div_angle_deg),
                "efficiency": float(_format_number(spec.nozzle.efficiency)),
                "erosionCoeff": float(_format_number(spec.nozzle.erosion_coeff)),
                "exit": _format_half_inches(spec.nozzle.exit_diameter_m),
                "slagCoeff": float(_format_number(spec.nozzle.slag_coeff)),
                "throat": _format_half_inches(spec.nozzle.throat_diameter_m),
                "throatLength": _format_half_inches(spec.nozzle.throat_length_m),
            },
            "propellant": {
                "density": float(_format_number(spec.propellant.density_kg_m3)),
                "name": spec.propellant.name,
                "tabs": [
                    {
                        "a": float(_format_number(tab.a)),
                        "k": float(_format_number(tab.k)),
                        "m": float(_format_number(tab.m)),
                        "maxPressure": float(_format_number(tab.max_pressure_pa)),
                        "minPressure": float(_format_number(tab.min_pressure_pa)),
                        "n": float(_format_number(tab.n)),
                        "t": float(_format_number(tab.t)),
                    }
                    for tab in spec.propellant.tabs
                ],
            },
        }
    }
    body = yaml.dump(
        payload,
        Dumper=_FloatDumper,
        default_flow_style=False,
        sort_keys=False,
    )
    return body.rstrip() + "\n" + _ric_footer()
