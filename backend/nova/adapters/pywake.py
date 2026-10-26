"""Optional PyWake NOJ adapter; the scientific environment is user managed.

Public APIs: https://topfarm.pages.windenergy.dtu.dk/PyWake/notebooks/WindTurbines.html
and https://topfarm.pages.windenergy.dtu.dk/pywake/api/Site.html.
"""
import json
import math
import tempfile
from pathlib import Path

from nova.adapters.base import (
    AdapterDescriptor,
    AdapterError,
    ExternalAdapter,
    PreparedCase,
    safe_artifact,
)
from nova.adapters.process import ProcessSpec, run_process
from nova.core.data import Port, canonical_json

IMPORTS = '''import json
from importlib.metadata import version
from py_wake import NOJ
from py_wake.site import UniformSite
from py_wake.wind_turbines import WindTurbine
from py_wake.wind_turbines.power_ct_functions import PowerCtTabular
'''
PROBE = IMPORTS + '''v = version('py-wake')
print(json.dumps({'available': True, 'compatible': v.split('.')[:2] == ['2', '6'],
                  'version': v, 'qualification': 'public API imports only; numerical qualification is separate',
                  'message': 'Adapter targets PyWake 2.6.x public APIs'}))
'''
RUNNER = IMPORTS + '''from pathlib import Path
import numpy as np
c = json.loads(Path('input.json').read_text())
t, w, layout = c['turbine'], c['wind'], c['layout']
wt = WindTurbine(name=t['name'], diameter=t['diameter_m'], hub_height=t['hub_height_m'],
    powerCtFunction=PowerCtTabular(t['wind_speed_m_s'], t['power_w'], 'W', t['ct']))
model = NOJ(UniformSite(p_wd=[1], ti=w['turbulence_intensity']), wt, k=0.1)
n, nd, ns = len(layout['x_m']), len(w['directions_deg']), len(w['speeds_m_s'])
power, speed = np.empty((n, nd, ns)), np.empty((n, nd, ns))
baseline = np.empty_like(power)
for d, direction in enumerate(w['directions_deg']):
    for s, ws in enumerate(w['speeds_m_s']):
        simulation = model(layout['x_m'], layout['y_m'], wd=[direction], ws=[ws])
        power[:, d, s] = simulation.Power.transpose('wt', 'wd', 'ws').values[:, 0, 0]
        speed[:, d, s] = simulation.WS_eff.transpose('wt', 'wd', 'ws').values[:, 0, 0]
        baseline[:, d, s] = float(np.asarray(wt.power(ws)).reshape(-1)[0])
output = {'power_w': power.tolist(), 'effective_speed_m_s': speed.tolist(),
          'power_without_wakes_w': baseline.tolist(), 'directions_deg': w['directions_deg'],
          'speeds_m_s': w['speeds_m_s'], 'probabilities': w['probabilities'],
          'program_version': version('py-wake')}
Path('output.json').write_text(json.dumps(output, allow_nan=False))
print('PyWake NOJ computation completed', flush=True)
'''


def numbers(value, label, minimum=None, maximum=None):
    if not isinstance(value, list) or not value:
        raise ValueError(f'{label} must be a nonempty numeric list')
    if any(type(v) not in (int, float) or not math.isfinite(v) or
           (minimum is not None and v < minimum) or (maximum is not None and v > maximum) for v in value):
        raise ValueError(f'Invalid {label}')
    return value


class PyWakeAdapter(ExternalAdapter):
    def describe(self):
        return AdapterDescriptor('pywake', 'PyWake', '1', 'Discrete flat-site NOJ wind farm analysis',
            'MIT (external PyWake; installed independently)', ('python_environment',),
            {'case': Port('wind_farm_case', 'SI', shape='record')},
            {'result': Port('wind_farm_result', 'SI', shape='record')})

    def probe(self, configuration):
        self._configuration(configuration)
        with tempfile.TemporaryDirectory() as directory:
            result = run_process(ProcessSpec(configuration.executable, ('-c', PROBE), 30), Path(directory))
        try:
            value = json.loads(result.log.strip().splitlines()[-1])
            if not isinstance(value, dict) or not isinstance(value.get('version'), str):
                raise ValueError('Missing version')
            return value
        except (ValueError, IndexError) as exc:
            raise AdapterError('Invalid PyWake probe response') from exc

    def _configuration(self, configuration):
        if configuration.environment_kind != 'python_environment' or configuration.options:
            raise ValueError('Select a Python environment; this adapter accepts no options')

    def validate(self, case, configuration):
        self._configuration(configuration)
        if not isinstance(case, dict) or set(case) - {'turbine', 'layout', 'wind', 'wake_model', 'timeout_seconds'} or not {'turbine', 'layout', 'wind', 'wake_model'} <= set(case) or case['wake_model'] != 'noj':
            raise ValueError('Expected turbine, layout, wind and wake_model=noj')
        timeout = case.get('timeout_seconds', 300)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 0 < timeout <= 3600:
            raise ValueError('timeout_seconds must be finite, positive and at most 3600')
        t, layout, w = case['turbine'], case['layout'], case['wind']
        if not all(isinstance(v, dict) for v in (t, layout, w)):
            raise ValueError('Case sections must be objects')
        if set(t) != {'name', 'diameter_m', 'hub_height_m', 'wind_speed_m_s', 'power_w', 'ct'} or set(layout) != {'x_m', 'y_m'} or set(w) != {'directions_deg', 'speeds_m_s', 'probabilities', 'turbulence_intensity'}:
            raise ValueError('Unknown or missing case quantities')
        if not isinstance(t['name'], str) or not 1 <= len(t['name']) <= 120:
            raise ValueError('Invalid turbine name')
        for section, key in ((t, 'diameter_m'), (t, 'hub_height_m'), (w, 'turbulence_intensity')):
            v = section[key]
            if type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
                raise ValueError(f'Invalid {key}')
        if w['turbulence_intensity'] > 1:
            raise ValueError('Turbulence intensity must be a fraction at most one')
        ws = numbers(t['wind_speed_m_s'], 'curve wind speeds', 0)
        power = numbers(t['power_w'], 'power curve', 0)
        ct = numbers(t['ct'], 'thrust coefficients', 0, 1)
        if not 2 <= len(ws) <= 512 or len(ws) != len(power) or len(ws) != len(ct) or any(a >= b for a, b in zip(ws, ws[1:])):
            raise ValueError('Curve requires matching arrays and strictly increasing wind speeds')
        x, y = numbers(layout['x_m'], 'layout x'), numbers(layout['y_m'], 'layout y')
        if len(x) != len(y) or len(x) > 128 or len(set(zip(x, y))) != len(x):
            raise ValueError('Layout requires 1–128 distinct turbine positions')
        directions = numbers(w['directions_deg'], 'wind directions', 0)
        speeds = numbers(w['speeds_m_s'], 'wind speeds', 0)
        if any(d >= 360 for d in directions) or len(set(directions)) != len(directions) or len(set(speeds)) != len(speeds):
            raise ValueError('Wind conditions must be distinct; directions in [0,360)')
        if min(speeds) < ws[0] or max(speeds) > ws[-1] or len(x)*len(directions)*len(speeds) > 8192:
            raise ValueError('Wind conditions exceed curve coverage or 8192 turbine-condition budget')
        p = w['probabilities']
        if not isinstance(p, list) or len(p) != len(directions) or any(len(numbers(row, 'joint probability', 0, 1)) != len(speeds) for row in p):
            raise ValueError('Probabilities require direction × speed shape')
        if not math.isclose(sum(map(sum, p)), 1, rel_tol=0, abs_tol=1e-9):
            raise ValueError('Joint probabilities must sum to one; no implicit normalization')

    def prepare(self, case, configuration, directory):
        self.validate(case, configuration)
        (directory / 'input.json').write_text(canonical_json(case))
        (directory / 'pywake_runner.py').write_text(RUNNER)
        return PreparedCase((ProcessSpec(configuration.executable, ('pywake_runner.py',), case.get('timeout_seconds', 300)),),
                            ('input.json', 'pywake_runner.py'), ('output.json',))

    def collect(self, directory, prepared):
        output = json.loads(safe_artifact(directory, 'output.json').read_text())
        output['_case'] = json.loads(safe_artifact(directory, 'input.json').read_text())
        return output

    def normalize(self, output):
        import numpy as np
        case = output['_case']
        self.validate(case, type('Configuration', (), {'environment_kind': 'python_environment', 'options': {}})())
        w = case['wind']
        for key in ('directions_deg', 'speeds_m_s', 'probabilities'):
            if output.get(key) != w[key]:
                raise AdapterError('Output conditions differ from submitted case')
        shape = (len(case['layout']['x_m']), len(w['directions_deg']), len(w['speeds_m_s']))
        arrays = {}
        for key in ('power_w', 'effective_speed_m_s', 'power_without_wakes_w'):
            try:
                array = np.asarray(output[key], dtype=float)
            except (ValueError, TypeError, KeyError) as exc:
                raise AdapterError('Invalid PyWake output array') from exc
            if array.shape != shape or not np.all(np.isfinite(array)) or np.any(array < 0):
                raise AdapterError('Invalid PyWake output shape or nonphysical value')
            arrays[key] = array
        weights = np.asarray(w['probabilities'])
        aep = (arrays['power_w'] * weights).sum(axis=(1, 2)) * 8760 / 1e9
        baseline = (arrays['power_without_wakes_w'] * weights).sum(axis=(1, 2)) * 8760 / 1e9
        total, reference = float(aep.sum()), float(baseline.sum())
        return {'kind': 'wind_farm_result', 'schema_version': 1, 'wake_model': 'noj',
                'assumptions': ['flat terrain', 'no shear', 'single turbine type', 'NOJ k=0.1', 'discrete joint probabilities', '8760 hours/year'],
                'axis_order': ['turbine', 'direction', 'speed'], 'layout': case['layout'],
                'directions_deg': w['directions_deg'], 'speeds_m_s': w['speeds_m_s'], 'probabilities': w['probabilities'],
                **{key: a.tolist() for key, a in arrays.items()},
                'aep_gwh': aep.tolist(), 'aep_without_wakes_gwh': baseline.tolist(),
                'total_aep_gwh': total, 'total_aep_without_wakes_gwh': reference,
                'wake_loss_fraction': (reference-total)/reference if reference > 0 else None,
                'program_version': output['program_version']}
