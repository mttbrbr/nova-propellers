"""Small versioned scientific contracts, independent of transport and storage."""
import hashlib
import json
from dataclasses import dataclass


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


@dataclass(frozen=True)
class Port:
    quantity: str
    units: str
    shape: str = 'scalar'
    frame: str | None = None
    time_domain: str = 'static'
    spatial_association: str | None = None
    sign_convention: str | None = None

    def compatible(self, other):
        return self == other


# Semantic compatibility must be established before unit conversion.
_CONVERSIONS = {('mm', 'm'): .001, ('m', 'mm'): 1000.,
                ('deg', 'rad'): 0.017453292519943295,
                ('rad', 'deg'): 57.29577951308232}


def convert(value, source: Port, target: Port):
    from dataclasses import replace
    if replace(source, units=target.units) != target:
        raise ValueError('Incompatible scientific quantities or metadata')
    if source.units == target.units:
        return value
    try:
        return value * _CONVERSIONS[(source.units, target.units)]
    except KeyError as exc:
        raise ValueError('No unambiguous unit conversion registered') from exc
