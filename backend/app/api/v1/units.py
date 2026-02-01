KG_PER_LB = 0.45359237
LB_PER_KG = 1.0 / KG_PER_LB
M_PER_IN = 0.0254
IN_PER_M = 1.0 / M_PER_IN


def lb_to_kg(value: float) -> float:
    return value * KG_PER_LB


def kg_to_lb(value: float) -> float:
    return value * LB_PER_KG


def in_to_m(value: float) -> float:
    return value * M_PER_IN


def m_to_in(value: float) -> float:
    return value * IN_PER_M


def kg_m3_to_lb_in3(value: float) -> float:
    return value * LB_PER_KG / (IN_PER_M ** 3)


def convert_mass_length_payload(value):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                item = convert_mass_length_payload(item)
            if isinstance(item, (int, float)):
                if key == "propellant_mass":
                    out["propellant_mass_lb"] = kg_to_lb(float(item))
                    continue
                if key == "propellant_length":
                    out["propellant_length_in"] = m_to_in(float(item))
                    continue
                if key == "density_kg_m3":
                    out["density_lb_in3"] = kg_m3_to_lb_in3(float(item))
                    continue
                if key.endswith("_kg"):
                    out[f"{key[:-3]}_lb"] = kg_to_lb(float(item))
                    continue
                if key.endswith("_m"):
                    out[f"{key[:-2]}_in"] = m_to_in(float(item))
                    continue
            out[key] = item
        return out
    if isinstance(value, list):
        return [convert_mass_length_payload(item) for item in value]
    return value
