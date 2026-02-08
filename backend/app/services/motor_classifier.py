import math
from typing import Dict, Optional, List

from pydantic import BaseModel

# --- PHYSICS CONSTANTS ---
G = 9.81
R_AIR = 287.05
GAMMA = 1.4
ISP_DEFAULT = 230.0
DT = 0.05

# --- INPUT MODELS ---


class CalibrationData(BaseModel):
    known_impulse_ns: float
    known_apogee_ft: float
    dry_mass_lbs: float


class ClassificationRequest(BaseModel):
    target_apogee_ft: float
    dry_mass_lbs: float
    diameter_in: float
    num_stages: int = 2
    calibration: Optional[CalibrationData] = None


# --- OUTPUT MODEL (Modified) ---


class SimplifiedStageInfo(BaseModel):
    role: str
    motor_class: str
    class_ceiling_ns: float  # <--- NOW RETURNS THE UPPER LIMIT


class SimplifiedMotorSolution(BaseModel):
    stages: List[SimplifiedStageInfo]


# --- HELPER: CLASS LIMITS ---


def get_class_info(ns: float) -> tuple[str, float]:
    """Returns (Class Letter, Upper Limit of that Class)"""
    if ns < 40960:
        return "O", 40960.0
    if ns < 81920:
        return "P", 81920.0
    if ns < 163840:
        return "Q", 163840.0
    if ns < 327680:
        return "R", 327680.0
    return "S", 655360.0


# --- PHYSICS ENGINE (Standard) ---


class Atmosphere:
    @staticmethod
    def get_density_and_speed_of_sound(altitude_m):
        if altitude_m < 11000:
            temp = 288.15 - 0.0065 * altitude_m
            pressure = 101325 * (temp / 288.15) ** 5.2558
        else:
            temp = 216.65
            pressure = 22632.1 * math.exp(-0.000157 * (altitude_m - 11000))
        if pressure < 0.1:
            pressure = 0.1
        density = pressure / (R_AIR * temp)
        speed_of_sound = math.sqrt(GAMMA * R_AIR * temp)
        return density, speed_of_sound


class DragModel:
    @staticmethod
    def get_cd(mach: float, efficiency_factor: float) -> float:
        base_cd = 0.5
        if mach < 0.8:
            base_cd = 0.55
        elif mach < 1.05:
            base_cd = 0.55 + (mach - 0.8) * 2.0
        elif mach < 1.5:
            base_cd = 1.05 - (mach - 1.05) * 0.3
        elif mach < 3.0:
            base_cd = 0.9 - (mach - 1.5) * 0.1
        else:
            base_cd = 0.75
        return base_cd * efficiency_factor


def simulate_flight(
    total_impulse_ns: float, rocket_params: Dict, efficiency_factor: float
) -> float:
    split = 0.60
    imp_boost = total_impulse_ns * split
    imp_sust = total_impulse_ns * (1 - split)

    mass_fuel_boost = imp_boost / (ISP_DEFAULT * G)
    mass_fuel_sust = imp_sust / (ISP_DEFAULT * G)

    t_burn_boost = 6.0
    thrust_boost = imp_boost / t_burn_boost
    t_burn_sust = 10.0
    thrust_sust = imp_sust / t_burn_sust

    t, alt, vel = 0.0, 0.0, 0.0
    mass = rocket_params["dry_mass"] + mass_fuel_boost + mass_fuel_sust
    booster_drop_mass = mass_fuel_boost * 0.15

    while vel >= 0 or t < (t_burn_boost + t_burn_sust):
        if alt < 0 and t > 1:
            break

        rho, sound_speed = Atmosphere.get_density_and_speed_of_sound(alt)
        mach = abs(vel) / sound_speed
        cd = DragModel.get_cd(mach, efficiency_factor)
        drag = 0.5 * rho * (vel**2) * rocket_params["area"] * cd

        thrust = 0.0
        if t < t_burn_boost:
            thrust = thrust_boost
            mass -= (mass_fuel_boost / t_burn_boost) * DT
        elif t < t_burn_boost + 2.0:
            thrust = 0.0
            if t >= t_burn_boost and t < t_burn_boost + DT:
                mass -= booster_drop_mass
        elif t < t_burn_boost + 2.0 + t_burn_sust:
            thrust = thrust_sust
            mass -= (mass_fuel_sust / t_burn_sust) * DT

        accel = (thrust - drag - (mass * G)) / mass
        vel += accel * DT
        alt += vel * DT
        t += DT
        if vel < 0 and t > (t_burn_boost + t_burn_sust + 2):
            break

    return alt * 3.28084


def calibrate_drag(specs: ClassificationRequest, params: Dict) -> float:
    if not specs.calibration:
        return 1.2
    min_eff, max_eff = 0.5, 3.0
    for _ in range(15):
        guess = (min_eff + max_eff) / 2
        apogee = simulate_flight(specs.calibration.known_impulse_ns, params, guess)
        if apogee > specs.calibration.known_apogee_ft:
            min_eff = guess
        else:
            max_eff = guess
    return (min_eff + max_eff) / 2


# --- MAIN EXECUTABLE ---


def calculate_motor_requirements(
    request: ClassificationRequest,
) -> SimplifiedMotorSolution:
    # 1. Setup
    params = {
        "dry_mass": request.dry_mass_lbs * 0.4536,
        "diameter": request.diameter_in * 0.0254,
        "area": math.pi * (request.diameter_in * 0.0254 / 2) ** 2,
    }

    # 2. Calibrate & Solve
    efficiency = calibrate_drag(request, params)

    min_imp, max_imp = 10000, 1000000
    best_imp = 0

    for _ in range(20):
        guess_imp = (min_imp + max_imp) / 2
        apogee = simulate_flight(guess_imp, params, efficiency)
        if abs(apogee - request.target_apogee_ft) < 1000:
            best_imp = guess_imp
            break
        if apogee < request.target_apogee_ft:
            min_imp = guess_imp
        else:
            max_imp = guess_imp

    # 3. Format Output (Return Limits)
    imp_boost = best_imp * 0.60
    imp_sust = best_imp * 0.40

    class_boost, limit_boost = get_class_info(imp_boost)
    class_sust, limit_sust = get_class_info(imp_sust)

    return SimplifiedMotorSolution(
        stages=[
            SimplifiedStageInfo(
                role="Booster", motor_class=class_boost, class_ceiling_ns=limit_boost
            ),
            SimplifiedStageInfo(
                role="Sustainer", motor_class=class_sust, class_ceiling_ns=limit_sust
            ),
        ]
    )
