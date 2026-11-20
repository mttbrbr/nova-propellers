"""Validation and execution of constraint-driven block workflows (schema 2).

A workflow is a typed DAG::

    {"schema_version": 2, "kind": "blocks", "name": "...",
     "nodes": [{"id": "rotor", "type": "rotor_hawt", "config": {...}, "position": {"x": 0, "y": 0}}],
     "edges": [{"source": "rotor", "source_port": "spec", "target": "op", "target_port": "spec"}]}

Execution is deterministic and headless. A failing block marks its dependants
``blocked``; a constraint block with ``on_violation: "stop"`` does the same
when a hard limit is violated, so infeasible designs never reach later stages.
"""
import contextvars
import copy
import math
import re
import time

import numpy as np

from nova.physics import rotors
from nova.physics.corrections import corrections_from
from nova.physics.vawt import METHODS as VAWT_METHODS

from . import economics, farm, fem, optimization, performance, structural
from .catalog import BLOCKS
from .constraints import evaluate_check, normalise, penalty, report
from .expressions import ExpressionError, evaluate

NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,63}$')
SPEC_ROOTS = {'geometry', 'operating', 'fluid', 'corrections', 'marine', 'section', 'method', 'azimuth_tubes'}
MAX_NODES, MAX_EDGES = 64, 256
_PROGRESS = contextvars.ContextVar('block_progress', default=None)
ROTOR_KIND = {'rotor_hawt': 'hawt', 'rotor_vawt': 'vawt', 'rotor_propeller': 'propeller', 'rotor_marine': 'marine'}


class BlockError(ValueError):
    pass


class _BudgetExhausted(Exception):
    pass


# ------------------------------------------------------------------ helpers

def set_path(spec, path, value):
    parts = path.split('.') if isinstance(path, str) else []
    if not parts or parts[0] not in SPEC_ROOTS or len(parts) > 2 or not all(NAME.match(p) for p in parts):
        raise BlockError(f'Unsupported specification path {path!r}')
    if len(parts) == 1:
        spec[parts[0]] = value
        return spec
    container = spec.setdefault(parts[0], {})
    if not isinstance(container, dict):
        raise BlockError(f'{parts[0]} is not a group')
    container[parts[1]] = value
    return spec


def get_path(spec, path):
    value = spec
    for part in path.split('.'):
        value = value.get(part) if isinstance(value, dict) else None
    return value


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise BlockError(f'{label} must be a finite number')
    return float(value)


def _parameter(item, label='Parameter'):
    name = item.get('name')
    if not isinstance(name, str) or not NAME.match(name):
        raise BlockError(f'{label} name must be an identifier (letters, digits, underscore)')
    value = _number(item.get('value'), f'{name} value')
    lo, hi = item.get('min'), item.get('max')
    if lo is not None and value < _number(lo, f'{name} minimum'):
        raise BlockError(f'{name} = {value:g} is below its minimum {lo:g}')
    if hi is not None and value > _number(hi, f'{name} maximum'):
        raise BlockError(f'{name} = {value:g} is above its maximum {hi:g}')
    return name, value


def _bind(spec, bindings, parameters):
    for path, expression in (bindings or {}).items():
        if not isinstance(expression, str):
            raise BlockError(f'Binding for {path} must be an expression')
        if parameters is None:
            raise BlockError(f'Binding {path} needs a connected parameters input')
        try:
            set_path(spec, path, evaluate(expression, parameters))
        except ExpressionError as exc:
            raise BlockError(f'Binding {path}: {exc}') from exc
    return spec


def _check_spec(spec):
    try:
        built, rotor, _ = rotors.build(spec)
        rotors.resolve_operating(built, rotor) if built.get('operating') else None
    except (KeyError, TypeError) as exc:
        raise BlockError(f'Incomplete rotor specification: {exc}') from exc
    return spec


def _metrics(spec):
    result = rotors.analyze(spec)
    values = rotors.scalar_outputs(result)
    values['converged'] = 1.0 if result['converged'] else 0.0
    return result, values


def _values_list(config):
    if config.get('values'):
        values = [_number(v, 'Sweep value') for v in config['values']]
    else:
        start, stop = _number(config.get('start'), 'Sweep start'), _number(config.get('stop'), 'Sweep stop')
        count = config.get('count', 5)
        if type(count) is not int or not 2 <= count <= 100:
            raise BlockError('Sweep count must be an integer in 2–100')
        values = np.linspace(start, stop, count).tolist()
    if not 1 <= len(values) <= 100:
        raise BlockError('A sweep needs 1–100 values')
    return values


# ------------------------------------------------------------------ validation

def validate(workflow):
    if not isinstance(workflow, dict) or workflow.get('schema_version') != 2 or workflow.get('kind') != 'blocks':
        raise BlockError('Block workflows use schema_version 2 and kind "blocks"')
    nodes, edges = workflow.get('nodes'), workflow.get('edges', [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise BlockError('Nodes and edges must be lists')
    if not 1 <= len(nodes) <= MAX_NODES or len(edges) > MAX_EDGES:
        raise BlockError(f'A workflow needs 1–{MAX_NODES} blocks and at most {MAX_EDGES} connections')
    lookup = {}
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not node['id'] or len(node['id']) > 64:
            raise BlockError('Every block needs a string id')
        if node['id'] in lookup:
            raise BlockError(f'Duplicate block id {node["id"]!r}')
        if node.get('type') not in BLOCKS:
            raise BlockError(f'Unknown block type {node.get("type")!r}')
        config = node.get('config', {})
        if not isinstance(config, dict):
            raise BlockError(f'Block {node["id"]}: configuration must be an object')
        allowed = set(BLOCKS[node['type']]['defaults'])
        unknown = set(config) - allowed
        if unknown:
            raise BlockError(f'Block {node["id"]}: unsupported settings {", ".join(sorted(unknown))}')
        lookup[node['id']] = node
    inbound = {nid: {} for nid in lookup}
    dependencies = {nid: set() for nid in lookup}
    for edge in edges:
        if not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) for k in ('source', 'source_port', 'target', 'target_port')):
            raise BlockError('Invalid connection structure')
        source, target = lookup.get(edge['source']), lookup.get(edge['target'])
        if not source or not target:
            raise BlockError('Connection references a missing block')
        out = next((p for p in BLOCKS[source['type']]['outputs'] if p['name'] == edge['source_port']), None)
        inp = next((p for p in BLOCKS[target['type']]['inputs'] if p['name'] == edge['target_port']), None)
        if not out or not inp:
            raise BlockError(f'Unknown port on connection {edge["source"]} → {edge["target"]}')
        if out['type'] != inp['type']:
            raise BlockError(f'{edge["source"]}.{out["name"]} ({out["type"]}) cannot feed {edge["target"]}.{inp["name"]} ({inp["type"]})')
        if edge['target_port'] in inbound[edge['target']]:
            raise BlockError(f'Input {edge["target"]}.{edge["target_port"]} already has a connection')
        inbound[edge['target']][edge['target_port']] = (edge['source'], edge['source_port'])
        dependencies[edge['target']].add(edge['source'])
    missing = [f'{nid}.{p["name"]}' for nid, node in lookup.items() for p in BLOCKS[node['type']]['inputs']
               if not p['optional'] and p['name'] not in inbound[nid]]
    if missing:
        raise BlockError(f'Unconnected required input: {", ".join(missing)}')
    order, remaining = [], dict(dependencies)
    while remaining:
        ready = sorted(nid for nid, deps in remaining.items() if deps <= set(order))
        if not ready:
            raise BlockError('Workflow contains a cycle')
        order.extend(ready)
        for nid in ready:
            del remaining[nid]
    return {'valid': True, 'order': order, 'inbound': inbound}


# ------------------------------------------------------------------ block handlers

def _rotor(node, args):
    kind = ROTOR_KIND[node['type']]
    config = node.get('config', {})
    spec = {'kind': kind}
    if config.get('geometry'):
        spec['geometry'] = copy.deepcopy(config['geometry'])
    if config.get('section'):
        spec['section'] = copy.deepcopy(config['section'])
    if config.get('sections'):
        spec['sections'] = copy.deepcopy(config['sections'])
    if config.get('method'):
        spec['method'] = config['method']
    spec = rotors.merged(spec)
    _bind(spec, config.get('bindings'), args.get('parameters'))
    return {'spec': _check_spec(spec)}


def _operating(node, args):
    spec = copy.deepcopy(args['spec'])
    config = node.get('config', {})
    if config.get('fluid'):
        spec['fluid'] = copy.deepcopy(config['fluid'])
    if config.get('operating'):
        spec['operating'] = copy.deepcopy(config['operating'])
    _bind(spec, config.get('bindings'), args.get('parameters'))
    return {'spec': _check_spec(spec)}


def _marine(node, args):
    spec = copy.deepcopy(args['spec'])
    if spec['kind'] != 'marine':
        raise BlockError('Hull & immersion applies to a marine propeller')
    spec['marine'] = {**rotors.DEFAULTS['marine']['marine'], **node.get('config', {})}
    return {'spec': spec}


def _corrections(node, args):
    spec = copy.deepcopy(args['spec'])
    vertical = node['type'] == 'corrections_vertical'
    if (spec['kind'] == 'vawt') != vertical:
        raise BlockError('VAWT corrections apply to vertical-axis rotors, axial corrections to the others')
    # Only the corrections that apply to the connected rotor family are taken.
    applicable = rotors.APPLICABLE_CORRECTIONS[spec['kind']]
    config = {**rotors.DEFAULTS[spec['kind']]['corrections'],
              **{k: v for k, v in node.get('config', {}).items() if k in applicable}}
    corrections_from('vertical' if vertical else 'axial', config)
    spec['corrections'] = config
    return {'spec': spec}


def _solver(node, args):
    spec = copy.deepcopy(args['spec'])
    config = node.get('config', {})
    method = config.get('method', 'auto')
    if method != 'auto':
        valid = VAWT_METHODS if spec['kind'] == 'vawt' else ('bemt',)
        if method not in valid:
            raise BlockError(f'Method {method} is not available for {spec["kind"]} rotors')
        spec['method'] = method
    if spec['kind'] == 'vawt' and config.get('azimuth_tubes'):
        spec['azimuth_tubes'] = int(config['azimuth_tubes'])
    result, values = _metrics(spec)
    return {'result': result, 'values': values}


def _curve(node, args):
    spec = args['spec']
    config = node.get('config', {})
    variable = None if config.get('variable', 'auto') == 'auto' else config['variable']
    values = None
    if config.get('start') is not None and config.get('stop') is not None:
        values = np.linspace(_number(config['start'], 'Curve start'), _number(config['stop'], 'Curve stop'),
                             int(config.get('points', 21))).tolist()
    points = config.get('points', 21)
    if type(points) is not int or not 3 <= points <= 81:
        raise BlockError('Curve points must be an integer in 3–81')
    curve = rotors.performance_curve(spec, variable=variable, values=values, points=points)
    record = {}
    if curve['optimum']:
        quantity = curve['optimum']['quantity']
        record[f'{quantity}_max'] = curve['optimum']['value']
        record[f'{curve["variable"]}_at_{quantity}_max'] = curve['optimum'][curve['variable']]
    return {'table': {'kind': 'performance_curve', 'variable': curve['variable'], 'rows': curve['rows'],
                      'optimum': curve['optimum'], 'betz_limit': curve['betz_limit'], 'rotor_kind': curve['kind']},
            'values': record}


def _checks(node, args):
    config = node.get('config', {})
    checks = config.get('checks', [])
    if not isinstance(checks, list) or len(checks) > 50:
        raise BlockError('Constraints must be a list of at most 50 checks')
    for check in checks:
        normalise(check)
    if config.get('on_violation', 'report') not in ('report', 'stop'):
        raise BlockError('on_violation must be report or stop')
    result = report(checks, args['values'])
    result['block'] = node['id']
    return {'values': args['values'], 'report': result}


def _sweep(node, args, cancelled):
    config = node.get('config', {})
    path = config.get('path')
    set_path({}, path, 0)
    checks = config.get('checks') or []
    rows = []
    for value in _values_list(config):
        if cancelled and cancelled():
            raise InterruptedError('Run cancelled')
        spec = set_path(copy.deepcopy(args['spec']), path, value)
        try:
            _, values = _metrics(spec)
            row = {'value': value, 'state': 'succeeded', **values}
            if checks:
                row['feasible'] = report(checks, values)['feasible']
        except ValueError as exc:
            row = {'value': value, 'state': 'failed', 'error': str(exc)}
        rows.append(row)
    return {'table': {'kind': 'sweep', 'variable': path, 'rows': rows}}


def _filter(node, args):
    checks = node.get('config', {}).get('checks') or []
    rows = [r for r in args['table']['rows'] if r.get('state', 'succeeded') == 'succeeded' and report(checks, r)['feasible']]
    return {'table': {**args['table'], 'rows': rows, 'filtered_from': len(args['table']['rows'])}}


def _select(node, args):
    config = node.get('config', {})
    sense = config.get('sense', 'maximize')
    if sense not in ('maximize', 'minimize'):
        raise BlockError('Sense must be maximize or minimize')
    rows = [r for r in args['table']['rows'] if r.get('state', 'succeeded') == 'succeeded'
            and (not config.get('feasible_only', True) or r.get('feasible', True))]
    scored = []
    for row in rows:
        try:
            scored.append((evaluate(config.get('objective', 'CP'), row), row))
        except ExpressionError:
            continue
    if not scored:
        raise BlockError('No row satisfies the selection')
    score, row = (max if sense == 'maximize' else min)(scored, key=lambda item: item[0])
    return {'values': {k: v for k, v in row.items() if isinstance(v, (int, float)) and not isinstance(v, bool)} | {'objective': score}}


def _optimizer(node, args, cancelled):
    from scipy.optimize import minimize
    config = node.get('config', {})
    variables = config.get('variables') or []
    if not 1 <= len(variables) <= 6:
        raise BlockError('Optimise 1–6 variables')
    bounds = []
    for item in variables:
        set_path({}, item.get('path'), 0)
        lo, hi = _number(item.get('min'), 'Variable minimum'), _number(item.get('max'), 'Variable maximum')
        if hi <= lo:
            raise BlockError(f'{item["path"]}: maximum must exceed minimum')
        bounds.append((lo, hi))
    sense = config.get('sense', 'maximize')
    if sense not in ('maximize', 'minimize'):
        raise BlockError('Sense must be maximize or minimize')
    objective = config.get('objective', 'CP')
    checks = config.get('checks') or []
    for check in checks:
        normalise(check)
    budget = config.get('max_evaluations', 80)
    if type(budget) is not int or not 2 <= budget <= 400:
        raise BlockError('Evaluation budget must be an integer in 2–400')
    method = config.get('method', 'cobyla')
    if method not in ('grid', 'nelder_mead', 'cobyla'):
        raise BlockError('Optimizer method must be grid, nelder_mead or cobyla')
    sign = -1.0 if sense == 'maximize' else 1.0
    history, cache = [], {}

    def physical(x):
        return [lo + float(np.clip(v, 0, 1)) * (hi - lo) for v, (lo, hi) in zip(x, bounds)]

    def run(x):
        key = tuple(round(float(v), 9) for v in np.clip(x, 0, 1))
        if key in cache:
            return cache[key]
        if len(history) >= budget:
            raise _BudgetExhausted
        if cancelled and cancelled():
            raise InterruptedError('Run cancelled')
        spec = copy.deepcopy(args['spec'])
        point = physical(x)
        for item, value in zip(variables, point):
            set_path(spec, item['path'], value)
        entry = {'evaluation': len(history) + 1, **{item['path']: v for item, v in zip(variables, point)}}
        try:
            _, values = _metrics(spec)
            score = evaluate(objective, values)
            rep = report(checks, values)
            entry.update(state='succeeded', objective=score, feasible=rep['feasible'], penalty=penalty(checks, values))
            outcome = (score, values, rep, spec)
        except (ValueError, ExpressionError) as exc:
            entry.update(state='failed', error=str(exc), feasible=False, penalty=1.0)
            outcome = None
        history.append(entry)
        cache[key] = outcome
        return outcome

    scale = [None]

    def merit(x):
        outcome = run(x)
        if outcome is None:
            return 1e6
        if scale[0] is None:
            scale[0] = max(abs(outcome[0]), 1e-9)
        return sign * outcome[0] / scale[0] + 1e3 * penalty(checks, outcome[1])

    def objective_only(x):
        outcome = run(x)
        if outcome is None:
            return 1e6
        if scale[0] is None:
            scale[0] = max(abs(outcome[0]), 1e-9)
        return sign * outcome[0] / scale[0]

    start = [float(np.clip((item.get('initial', (lo + hi) / 2) - lo) / (hi - lo), 0, 1))
             for item, (lo, hi) in zip(variables, bounds)]
    try:
        if method == 'grid':
            levels = int(config.get('grid_levels', 5))
            while levels > 2 and levels ** len(variables) > budget:
                levels -= 1
            axes = np.meshgrid(*[np.linspace(0, 1, levels)] * len(variables), indexing='ij')
            for point in np.stack([a.ravel() for a in axes], axis=1):
                run(point)
        elif method == 'nelder_mead':
            minimize(merit, start, method='Nelder-Mead', options={'maxfev': budget, 'xatol': 1e-3, 'fatol': 1e-5})
        else:
            def margin(i):
                def g(x):
                    outcome = run(x)
                    if outcome is None:
                        return -1.0
                    item = evaluate_check(checks[i], outcome[1])
                    return item['margin'] if item['margin'] is not None else -1.0
                return g
            constraints = [{'type': 'ineq', 'fun': (lambda x, j=j: x[j])} for j in range(len(variables))]
            constraints += [{'type': 'ineq', 'fun': (lambda x, j=j: 1 - x[j])} for j in range(len(variables))]
            constraints += [{'type': 'ineq', 'fun': margin(i)} for i, c in enumerate(checks) if normalise(c)['severity'] == 'hard']
            minimize(objective_only,
                     start, method='COBYLA', constraints=constraints,
                     options={'maxiter': budget, 'rhobeg': 0.25, 'tol': 1e-4})
    except _BudgetExhausted:
        pass
    best = None
    for entry in history:
        if entry['state'] != 'succeeded':
            continue
        rank = (0 if entry['feasible'] else 1, entry['penalty'], sign * entry['objective'])
        if best is None or rank < best[0]:
            best = (rank, entry)
    if best is None:
        raise BlockError('No optimisation evaluation succeeded')
    entry = best[1]
    spec = copy.deepcopy(args['spec'])
    for item in variables:
        set_path(spec, item['path'], entry[item['path']])
    _, values = _metrics(spec)
    values = {**values, 'objective': entry['objective'], 'feasible': 1.0 if entry['feasible'] else 0.0,
              'evaluations': float(len(history))}
    for item in variables:
        values[item['path'].split('.')[-1]] = entry[item['path']]
    return {'spec': spec, 'values': values,
            'history': {'kind': 'optimization', 'variables': [v['path'] for v in variables], 'objective': objective,
                        'sense': sense, 'method': method, 'rows': history, 'best_evaluation': entry['evaluation']}}


def _report(node, args):
    return {'report': {'title': node.get('config', {}).get('title', 'Design summary'),
                       'values': args.get('a'), 'table': args.get('b'),
                       'checks': [r for r in (args.get('c'), args.get('d')) if r]}}


def _parameter_block(node, _args):
    name, value = _parameter(node.get('config', {}))
    return {'value': {name: value}}


def _parameter_set(node, _args):
    items = node.get('config', {}).get('values') or []
    if not 1 <= len(items) <= 64:
        raise BlockError('A parameter set holds 1–64 values')
    return {'values': dict(_parameter(item) for item in items)}


def _expression(node, args):
    values = dict(args['values'])
    for item in node.get('config', {}).get('assignments') or []:
        name = item.get('name')
        if not isinstance(name, str) or not NAME.match(name):
            raise BlockError('Expression results need identifier names')
        values[name] = evaluate(item.get('expression', ''), values)
    return {'values': values}


STATS = ('mean', 'min', 'max', 'std', 'final')


def _openfast_case(node, _args):
    from nova.adapters.base import AdapterError
    from nova.adapters.openfast import inspect_openfast_case
    config = node.get('config', {})
    case = {key: config[key] for key in ('case_directory', 'input_file', 'output_file', 'timeout_seconds') if key in config}
    try:
        inspect_openfast_case(case)
    except AdapterError as exc:
        raise BlockError(str(exc)) from exc
    return {'case': case}


def _window_statistics(data, start):
    time = np.asarray(data['time_s'], dtype=float)
    values = np.asarray(data['values'], dtype=float)
    keep = time >= start
    if not keep.any():
        raise BlockError(f'start_time_s {start:g} is after the last output sample ({time[-1]:g} s)')
    window = values[keep]
    return {c['name']: {'units': c['units'], 'mean': float(window[:, i].mean()), 'min': float(window[:, i].min()),
                        'max': float(window[:, i].max()), 'std': float(window[:, i].std()), 'final': float(window[-1, i])}
            for i, c in enumerate(data['channels'])}, int(keep.sum())


def _openfast_integration(config):
    from nova.infrastructure import library
    integrations = [r for r in library.list_records('integration') if r.get('adapter_id') == 'openfast']
    chosen = config.get('integration_id') or ''
    integration = next((r for r in integrations if r['id'] == chosen), None) if chosen else (integrations[0] if integrations else None)
    if integration is None:
        raise BlockError('No OpenFAST executable is configured: add one in Settings → Integrations')
    return integration


def _throttled_log():
    report = _PROGRESS.get()
    last = [0.0]

    def log(text):  # throttled: OpenFAST prints one line per time step
        if report and time.monotonic() - last[0] > 0.5 and text.strip():
            last[0] = time.monotonic()
            report(text.strip().splitlines()[-1][:120])
    return log


def _openfast_linearization(node, args, cancelled):
    import shutil
    import uuid
    from pathlib import Path

    import database
    from nova.adapters import openfast_lin
    from nova.adapters.base import AdapterError, execute_adapter
    from nova.adapters.openfast import copy_openfast_case
    from nova.adapters.registry import get
    from nova.application.external import configuration
    config = node.get('config', {})
    azimuths = config.get('azimuths', 12)
    if type(azimuths) is not int or not 4 <= azimuths <= 72:
        raise BlockError('azimuths must be an integer in 4–72')
    settle = _number(config.get('settle_time_s', 5.0), 'settle_time_s')
    if not 0 <= settle <= 600:
        raise BlockError('settle_time_s must be in 0–600 s')
    rpm = config.get('rpm')
    rpm = None if rpm is None else _number(rpm, 'rpm')
    blades = config.get('blades', 3)
    if type(blades) is not int or not 3 <= blades <= 10:
        raise BlockError('blades must be an integer in 3–10 (the multi-blade transformation needs three or more)')
    integration = _openfast_integration(config)
    root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
    root.mkdir(parents=True)
    try:
        edited = root / 'linearization_source'
        shutil.copytree(Path(args['case']['case_directory']), edited,
                        ignore=shutil.ignore_patterns('*.out', '*.outb', '*.lin', '*.sum', '*.ech'))
        rpm, times = openfast_lin.prepare(edited, args['case']['input_file'], azimuths=azimuths, settle_s=settle, rpm=rpm)
        frozen = copy_openfast_case({**args['case'], 'case_directory': str(edited)}, root / 'source_case')
        output = execute_adapter(get('openfast'), configuration(integration), frozen, root, cancelled=cancelled, on_log=_throttled_log())
        found = openfast_lin.modes(openfast_lin.read_directory(Path(output['working_directory']) / 'case', blades), blades)
    except (AdapterError, openfast_lin.LinearizationError, OSError) as exc:
        raise BlockError(str(exc)) from exc
    return linearization_outputs(found, rpm, times, azimuths, settle, args.get('modal'))


def linearization_outputs(found, rpm, times, azimuths, settle, modal_input):
    from nova.adapters import openfast_lin
    rows = [{'mode': m['id'], 'frequency_hz': m['frequency_hz'], 'damping_ratio': m['damping_ratio'], 'whirl': m['whirl']} for m in found]
    record = {f'of_{m["id"]}_hz': m['frequency_hz'] for m in found}
    record['rpm'] = rpm
    notes = [f'OpenFAST structural linearisation at {rpm:g} rpm: ElastoDyn with aerodynamics, inflow, control and gravity off, '
             f'{azimuths} azimuths over one revolution from t = {settle:g} s, multi-blade coordinates averaged over azimuth (MBC3). '
             'Labels come from the largest state amplitude and can be wrong for higher tower modes.']
    comparison = []
    if modal_input is not None:
        campbell = modal_input.get('campbell') or {}
        if campbell.get('coupling') != 'mbc':
            notes.append('The connected Campbell diagram is not coupled (set coupling to mbc): no mode-by-mode comparison')
        else:
            if not campbell['rpm'][0] <= rpm <= campbell['rpm'][-1]:
                raise BlockError(f'{rpm:g} rpm is outside the Campbell diagram speed range')
            curves = [{**c, 'rpm': campbell['rpm']} for c in campbell['curves']]
            comparison = openfast_lin.compare(found, curves, rpm)
            if comparison:
                record['max_difference_pct'] = max(abs(p['difference_pct']) for p in comparison)
                notes.append('Modes paired with Nova by nearest frequency, preferring the same family and whirl. ElastoDyn uses '
                             'polynomial assumed modes (Euler–Bernoulli), Nova a 3-D Timoshenko beam: differences grow for '
                             'higher modes. Damping definitions differ (ElastoDyn applies it per assumed mode).')
    return {'table': {'kind': 'linearization', 'rows': rows, 'comparison': comparison, 'rpm': rpm, 'times_s': times},
            'values': record, 'notes': notes}


def _openfast_run(node, args, cancelled):
    import uuid

    import database
    from nova.adapters.base import AdapterError, execute_adapter
    from nova.adapters.openfast import copy_openfast_case
    from nova.adapters.registry import get
    from nova.application.external import configuration
    config = node.get('config', {})
    start = _number(config.get('start_time_s', 0.0), 'start_time_s')
    wanted = config.get('statistics', [])
    if not isinstance(wanted, list) or len(wanted) > 50:
        raise BlockError('statistics must be a list of at most 50 entries')
    for item in wanted:
        if item.get('stat') not in STATS or not NAME.match(str(item.get('name', ''))) or not item.get('channel'):
            raise BlockError(f'Each statistic needs a channel, a name and a stat in {", ".join(STATS)}')
    integration = _openfast_integration(config)
    root = database.DB_PATH.parent / 'external-runs' / str(uuid.uuid4())
    root.mkdir(parents=True)
    try:
        frozen = copy_openfast_case(args['case'], root / 'source_case')
        output = execute_adapter(get('openfast'), configuration(integration), frozen, root, cancelled=cancelled, on_log=_throttled_log())
    except AdapterError as exc:
        raise BlockError(str(exc)) from exc
    stats, samples = _window_statistics(output['data'], start)
    record = {}
    for item in wanted:
        if item['channel'] not in stats:
            raise BlockError(f'Channel {item["channel"]} is not in the OpenFAST output')
        record[item['name']] = stats[item['channel']][item['stat']]
    rows = [{'channel': name, **stat} for name, stat in stats.items()]
    return {'table': {'kind': 'openfast_statistics', 'rows': rows, 'window_start_s': start, 'samples': samples,
                      'source': output['data']['source'], 'working_directory': output['working_directory']},
            'values': record}


def _structure_block(kind):
    def handler(node, _args):
        from nova.adapters import openfast_structure as structure
        build = {'hub': structure.hub_record, 'nacelle': structure.nacelle_record, 'tower': structure.tower_record,
                 'blade': structure.blade_record}[kind]
        try:
            return {kind: build(node.get('config', {}))}
        except structure.StructureError as exc:
            raise BlockError(str(exc)) from exc
    return handler


def _openfast_rotor_case(node, args):
    import shutil
    import uuid

    import database
    from nova.adapters.openfast_case import DOF_SETTINGS, SETTINGS, CaseError, write_case
    config = node.get('config', {})
    settings = {k: config[k] for k in (*SETTINGS, *DOF_SETTINGS) if k in config}
    structure = {k: args.get(k) for k in ('hub', 'nacelle', 'tower', 'blade')}
    parent = database.DB_PATH.parent / 'generated-cases'
    parent.mkdir(parents=True, exist_ok=True)
    scratch = parent / f'.tmp-{uuid.uuid4().hex}'
    try:
        info = write_case(args['spec'], scratch, settings, structure)
        final = parent / info['case_hash'][:20]
        if final.exists():
            shutil.rmtree(scratch)
        else:
            scratch.rename(final)
    except (CaseError, ValueError, KeyError) as exc:
        shutil.rmtree(scratch, ignore_errors=True)
        raise BlockError(str(exc)) from exc
    result = rotors.analyze(args['spec'])
    reference = {f'nova_{k}': v for k, v in rotors.scalar_outputs(result).items() if k in ('power_w', 'thrust_n', 'torque_nm', 'cp', 'ct')}
    for name, value in (info['frequencies_hz'] or {}).items():
        reference[f'nova_{name}_hz'] = value
    case = {'case_directory': str(final.resolve()), 'input_file': info['input_file'], 'output_file': info['output_file'],
            'timeout_seconds': float(config.get('timeout_seconds', 600.0))}
    return {'case': case, 'reference': reference, 'notes': [f'{info["model"].capitalize()} OpenFAST model', *info['assumptions']]}


HANDLERS = {
    'parameter': _parameter_block, 'parameter_set': _parameter_set, 'expression': _expression,
    'merge': lambda node, args: {'values': {**args['a'], **args['b']}},
    'constraint': _checks, 'design_checks': _checks, 'filter': _filter, 'select': _select, 'report': _report,
    'rotor_hawt': _rotor, 'rotor_vawt': _rotor, 'rotor_propeller': _rotor, 'rotor_marine': _rotor,
    'operating_point': _operating, 'marine_conditions': _marine,
    'corrections_axial': _corrections, 'corrections_vertical': _corrections,
    'solver': _solver, 'performance_curve': _curve, 'openfast_case': _openfast_case,
    'openfast_rotor_case': _openfast_rotor_case,
    'hub': _structure_block('hub'), 'nacelle': _structure_block('nacelle'), 'tower': _structure_block('tower'),
    'blade_structure': _structure_block('blade'),
    'point_mass': structural.attachment_handler('point_mass'), 'spring_damper': structural.attachment_handler('spring_damper'),
    'blade_modes': structural.blade_modes, 'rotating_blade_modes': lambda node, args: structural.blade_modes(node, args, rotating=True),
    'tower_modes': structural.tower_modes, 'campbell': structural.campbell,
    'operating_strategy': performance.operating_strategy,
    'annual_energy': economics.annual_energy, 'cost_model': economics.cost_model,
    'blade_layup': fem.blade_layup,
    'farm_turbine': farm.farm_turbine, 'farm_layout': farm.farm_layout, 'wind_climate': farm.wind_climate,
}
LONG = {'sweep': _sweep, 'optimizer': _optimizer, 'openfast_run': _openfast_run, 'openfast_linearization': _openfast_linearization,
        'performance_map': performance.performance_map, 'cp_flexible': performance.cp_flexible,
        'design_optimizer': optimization.design_optimizer, 'pareto_optimizer': optimization.pareto_optimizer,
        'multi_fidelity': optimization.multi_fidelity, 'calculix_blade_modes': fem.calculix_blade_modes,
        'wind_farm': farm.wind_farm, 'dust_rotor': farm.dust_rotor}
SUBGRAPH = {'design_optimizer', 'pareto_optimizer', 'multi_fidelity'}


def _schedule(checked, lookup):
    """Topological order in which the optimisers that re-run their downstream chain wait until every other ready
    block has run, so the inputs of that chain coming from other branches exist."""
    deps = {nid: {src for src, _ in checked['inbound'][nid].values()} for nid in lookup}
    done, order = set(), []
    while len(order) < len(lookup):
        ready = sorted(n for n in lookup if n not in done and deps[n] <= done)
        normal = [n for n in ready if lookup[n]['type'] not in SUBGRAPH]
        pick = (normal or ready)[0]
        order.append(pick)
        done.add(pick)
    return order


def _downstream(nid, checked, lookup, order, outputs, cancelled):
    """Evaluator of the blocks downstream of an optimiser for candidate outputs of that optimiser."""
    children = {}
    for target, ports in checked['inbound'].items():
        for src, _ in ports.values():
            children.setdefault(src, set()).add(target)
    reach, stack = set(), [nid]
    while stack:
        for child in children.get(stack.pop(), ()):
            if child not in reach:
                reach.add(child)
                stack.append(child)
    chain = [n for n in order if n in reach]
    for m in chain:
        if lookup[m]['type'] in SUBGRAPH:
            raise BlockError(f'Optimiser {m} is downstream of optimiser {nid}: nested optimisation is not supported')

    def evaluate_chain(own):
        local = {**outputs, nid: own}
        record, feasible, violation = {}, True, 0.0
        for m in chain:
            node = lookup[m]
            inbound = checked['inbound'][m]
            missing = sorted({src for src, _ in inbound.values() if src not in local})
            if missing:
                raise BlockError(f'{m} needs {", ".join(missing)}, which did not run before the optimiser')
            args = {port: local[src][out] for port, (src, out) in inbound.items()}
            result = LONG[node['type']](node, args, cancelled) if node['type'] in LONG else HANDLERS[node['type']](node, args)
            local[m] = result
            values = result.get('values')
            if isinstance(values, dict):
                record.update({k: float(v) for k, v in values.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
            if node['type'] in ('constraint', 'design_checks') and not result['report']['feasible']:
                feasible = False
                violation += penalty(node.get('config', {}).get('checks') or [], args['values'])
        return record, feasible, violation
    return evaluate_chain


def execute(workflow, *, progress=None, cancelled=None):
    checked = validate(workflow)
    lookup = {node['id']: node for node in workflow['nodes']}
    checked['order'] = _schedule(checked, lookup)
    outputs, blocks, reports = {}, {}, []
    for index, nid in enumerate(checked['order']):
        if cancelled and cancelled():
            raise InterruptedError('Run cancelled')
        node = lookup[nid]
        upstream = {src for src, _ in checked['inbound'][nid].values()}
        stopped = [src for src in upstream if blocks[src]['status'] in ('failed', 'blocked', 'violated')]
        if stopped:
            blocks[nid] = {'status': 'blocked', 'error': f'Waiting on {", ".join(sorted(stopped))}'}
            continue
        args = {port: outputs[src][out] for port, (src, out) in checked['inbound'][nid].items()}
        started = time.perf_counter()
        if progress:
            progress({'node': nid, 'progress': index / len(checked['order']), 'message': f'{nid}: running'})
        token = _PROGRESS.set(lambda text: progress({'node': nid, 'progress': index / len(checked['order']), 'message': f'{nid}: {text}'}) if progress else None)
        try:
            if node['type'] in SUBGRAPH:
                chain = optimization.DOWNSTREAM.set(_downstream(nid, checked, lookup, checked['order'], outputs, cancelled))
                try:
                    result = LONG[node['type']](node, args, cancelled)
                finally:
                    optimization.DOWNSTREAM.reset(chain)
            elif node['type'] in LONG:
                result = LONG[node['type']](node, args, cancelled)
            else:
                result = HANDLERS[node['type']](node, args)
            status = 'succeeded'
            if node['type'] in ('constraint', 'design_checks'):
                reports.append(result['report'])
                if not result['report']['feasible'] and node.get('config', {}).get('on_violation') == 'stop':
                    status = 'violated'
            outputs[nid] = result
            blocks[nid] = {'status': status, 'outputs': result, 'seconds': round(time.perf_counter() - started, 4)}
        except InterruptedError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            message = str(exc) if isinstance(exc, ValueError) else f'Invalid configuration: {exc}'
            blocks[nid] = {'status': 'failed', 'error': message, 'seconds': round(time.perf_counter() - started, 4)}
        finally:
            _PROGRESS.reset(token)
        if progress:
            progress({'node': nid, 'progress': (index + 1) / len(checked['order']), 'message': f'{nid}: {blocks[nid]["status"]}'})
    statuses = [b['status'] for b in blocks.values()]
    status = 'succeeded' if all(s == 'succeeded' for s in statuses) else ('failed' if 'failed' in statuses else 'stopped')
    return {'schema_version': 2, 'status': status, 'feasible': all(r['feasible'] for r in reports) if reports else None,
            'order': checked['order'], 'blocks': blocks, 'reports': reports}
