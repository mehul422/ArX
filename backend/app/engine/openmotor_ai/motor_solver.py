import math


class MotorSolver:
    """
    Utility to estimate required total impulse for a target apogee.
    """

    def __init__(self):
        self.g0 = 9.81  # m/s^2
        self.rho = 1.225  # kg/m^3
        # Upper limits for each class (Ns)
        self.motor_map = [
            (0.3125, "Micro"),
            (0.625, "1/4A"),
            (1.25, "1/2A"),
            (2.5, "A"),
            (5.0, "B"),
            (10.0, "C"),
            (20.0, "D"),
            (40.0, "E"),
            (80.0, "F"),
            (160.0, "G"),
            (320.0, "H"),
            (640.0, "I"),
            (1280.0, "J"),
            (2560.0, "K"),
            (5120.0, "L"),
            (10240.0, "M"),
            (20480.0, "N"),
            (40960.0, "O"),
            (81920.0, "P"),
            (163840.0, "Q"),
            (327680.0, "R"),
            (655360.0, "S"),
        ]

    def _get_classification(self, impulse_ns: float) -> str:
        for limit, letter in self.motor_map:
            if impulse_ns <= limit:
                return letter
        return "S+"

    def _simulate_flight(
        self, impulse: float, dry_mass: float, diameter: float, cd: float, isp: float
    ) -> float:
        propellant_mass = impulse / (isp * self.g0)
        wet_mass = dry_mass + propellant_mass

        avg_thrust_guess = (wet_mass * self.g0) * 8.0
        burn_time = impulse / avg_thrust_guess

        dt = 0.05
        t = 0.0
        v = 0.0
        h = 0.0

        area = math.pi * (diameter / 2) ** 2

        while t < burn_time:
            current_mass = wet_mass - ((propellant_mass / burn_time) * t)
            drag = 0.5 * self.rho * (v**2) * cd * area
            gravity = current_mass * self.g0
            thrust = avg_thrust_guess
            net_force = thrust - drag - gravity
            a = net_force / current_mass
            v += a * dt
            h += v * dt
            t += dt

        while v > 0:
            drag = 0.5 * self.rho * (v**2) * cd * area
            gravity = dry_mass * self.g0
            net_force = -drag - gravity
            a = net_force / dry_mass
            v += a * dt
            h += v * dt
            if h < 0:
                break
        return h

    def solve(
        self,
        target_altitude_m: float,
        dry_mass_kg: float,
        diameter_m: float,
        cd: float,
        isp: float,
    ) -> dict[str, float | str]:
        min_impulse = 1.0
        max_impulse = 200000.0
        tolerance = 1.0
        found_impulse = None
        apogee = 0.0

        for _ in range(70):
            mid_impulse = (min_impulse + max_impulse) / 2
            apogee = self._simulate_flight(
                mid_impulse, dry_mass_kg, diameter_m, cd, isp
            )
            if abs(apogee - target_altitude_m) < tolerance:
                found_impulse = mid_impulse
                break
            if apogee < target_altitude_m:
                min_impulse = mid_impulse
            else:
                max_impulse = mid_impulse

        if found_impulse is None:
            found_impulse = (min_impulse + max_impulse) / 2

        propellant_mass = found_impulse / (isp * self.g0)
        return {
            "impulse_required": float(round(found_impulse, 2)),
            "class": self._get_classification(found_impulse),
            "propellant_mass_kg": float(round(propellant_mass, 3)),
            "estimated_apogee_m": float(round(apogee, 2)),
        }
