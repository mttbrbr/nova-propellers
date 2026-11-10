"""Working-fluid properties for air and water rotors.

Values are nominal reference properties; every field can be overridden so a
study can represent the real site (altitude, temperature, salinity).
"""
import math
from dataclasses import asdict, dataclass

GRAVITY = 9.80665
STANDARD_ATMOSPHERE_PA = 101325.0


@dataclass(frozen=True)
class Fluid:
    name: str
    density_kg_m3: float
    viscosity_pa_s: float
    speed_of_sound_m_s: float
    vapour_pressure_pa: float | None = None
    ambient_pressure_pa: float = STANDARD_ATMOSPHERE_PA

    def __post_init__(self):
        for key in ('density_kg_m3', 'viscosity_pa_s', 'speed_of_sound_m_s', 'ambient_pressure_pa'):
            value = getattr(self, key)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'Fluid {key} must be finite and positive')
        if self.vapour_pressure_pa is not None and not 0 <= self.vapour_pressure_pa < self.ambient_pressure_pa:
            raise ValueError('Vapour pressure must be non-negative and below ambient pressure')

    @property
    def is_liquid(self):
        return self.vapour_pressure_pa is not None

    def to_dict(self):
        return asdict(self)


# Air: ISA sea level, 15 °C. Water: 15 °C (ITTC 2011 fresh and sea water tables).
PRESETS = {
    'air': Fluid('air', 1.225, 1.81e-5, 340.3),
    'fresh_water': Fluid('fresh_water', 999.1, 1.138e-3, 1465.0, vapour_pressure_pa=1705.0),
    'sea_water': Fluid('sea_water', 1025.9, 1.220e-3, 1507.0, vapour_pressure_pa=1705.0),
}


def fluid_from(config):
    """Build a fluid from a preset name plus optional overrides."""
    if isinstance(config, Fluid):
        return config
    config = dict(config or {})
    preset = config.pop('preset', 'air')
    if preset not in PRESETS:
        raise ValueError(f'Unknown fluid preset {preset!r}')
    allowed = set(asdict(PRESETS[preset])) - {'name'}
    unknown = set(config) - allowed
    if unknown:
        raise ValueError(f'Unsupported fluid properties: {", ".join(sorted(unknown))}')
    values = {**asdict(PRESETS[preset]), **{k: float(v) for k, v in config.items() if v is not None}}
    return Fluid(**values)
