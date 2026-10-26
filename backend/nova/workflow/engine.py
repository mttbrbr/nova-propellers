"""Deterministic typed DAG execution, usable without HTTP or a GUI."""
import copy
import math
import uuid
from dataclasses import asdict

from nova.application.analysis import run_propeller_analysis
from nova.application.geometry import create_propeller_geometry
from nova.core.data import Port, content_hash
from nova.core.polars import PolarProvider

DESIGN = Port('propeller_design', 'SI', shape='record')
GEOMETRY = Port('rotor_geometry', 'm', shape='radial', frame='rotor', spatial_association='blade')
RESULT = Port('aerodynamic_result', 'SI', shape='record', frame='rotor')
WIND_CASE = Port('wind_farm_case', 'SI', shape='record')
WIND_RESULT = Port('wind_farm_result', 'SI', shape='record')
FAST_CASE = Port('openfast_case', 'native', shape='record')
FAST_RESULT = Port('time_series_result', 'native', shape='record', time_domain='time_series')
EXTERNAL_TYPES = {'pywake_input', 'pywake', 'openfast_input', 'openfast'}
REGISTRY = {
    'parameters': {'inputs': {}, 'outputs': {'design': DESIGN}},
    'sizing': {'inputs': {'design': DESIGN}, 'outputs': {'design': DESIGN}},
    'geometry': {'inputs': {'design': DESIGN}, 'outputs': {'geometry': GEOMETRY}},
    'analysis': {'inputs': {'geometry': GEOMETRY}, 'outputs': {'result': RESULT}},
    'collect': {'inputs': {'result': RESULT}, 'outputs': {'result': RESULT}},
    'export': {'inputs': {'result': RESULT}, 'outputs': {'result': RESULT}},
    'pywake_input': {'inputs': {}, 'outputs': {'case': WIND_CASE}},
    'pywake': {'inputs': {'case': WIND_CASE}, 'outputs': {'result': WIND_RESULT}},
    'openfast_input': {'inputs': {}, 'outputs': {'case': FAST_CASE}},
    'openfast': {'inputs': {'case': FAST_CASE}, 'outputs': {'result': FAST_RESULT}},
}


def registry():
    return [{'id': key, **{direction: {name: asdict(port) for name, port in spec[direction].items()}
                          for direction in ('inputs', 'outputs')}} for key, spec in REGISTRY.items()]


def template(model='bemt'):
    return {'schema_version': 1, 'id': 'propeller-default', 'template': 'propeller-v1',
            'nodes': [{'id': 'parameters', 'type': 'parameters', 'config': {}},
                      {'id': 'sizing', 'type': 'sizing', 'config': {'mode': 'manual'}},
                      {'id': 'geometry', 'type': 'geometry', 'config': {}},
                      {'id': 'analysis', 'type': 'analysis', 'config': {'model': model}},
                      {'id': 'results', 'type': 'collect', 'config': {}}],
            'edges': [{'source': a, 'source_port': out, 'target': b, 'target_port': inp}
                      for a, out, b, inp in [('parameters', 'design', 'sizing', 'design'),
                                           ('sizing', 'design', 'geometry', 'design'),
                                           ('geometry', 'geometry', 'analysis', 'geometry'),
                                           ('analysis', 'result', 'results', 'result')]]}


def external_template(adapter_id):
    if adapter_id not in ('pywake', 'openfast'):
        raise ValueError('Unknown external workflow')
    return {'schema_version': 1, 'id': adapter_id + '-default', 'template': adapter_id + '-v1',
            'nodes': [{'id': 'case', 'type': adapter_id + '_input', 'config': {}},
                      {'id': 'solver', 'type': adapter_id, 'config': {}}],
            'edges': [{'source': 'case', 'source_port': 'case', 'target': 'solver', 'target_port': 'case'}]}


def clone(workflow):
    result = copy.deepcopy(workflow)
    result.update(id=str(uuid.uuid4()), name='Customized propeller workflow')
    result['template_origin'] = result.pop('template', result.get('template_origin'))
    return result


def validate(workflow):
    if workflow.get('schema_version') != 1:
        raise ValueError('Unsupported workflow schema')
    nodes = workflow.get('nodes', [])
    edges = workflow.get('edges', [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError('Nodes and edges must be lists')
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get('id'), str) or not isinstance(node.get('type'), str) or not isinstance(node.get('config', {}), dict):
            raise ValueError('Invalid node structure')
    if any(not isinstance(e, dict) or any(not isinstance(e.get(k), str) for k in ('source', 'source_port', 'target', 'target_port')) for e in edges):
        raise ValueError('Invalid connection structure')
    if any(n['type'] in EXTERNAL_TYPES for n in nodes):
        kinds = [n['type'] for n in nodes]
        if len(kinds) != 2 or set(kinds) not in ({'pywake_input', 'pywake'}, {'openfast_input', 'openfast'}):
            raise ValueError('External workflows currently require one case and one matching adapter node')
    if not nodes or len(nodes) > 64 or len(workflow.get('edges', [])) > 256:
        raise ValueError('Workflow requires 1–64 nodes and at most 256 edges')
    if sum(n['type'] == 'geometry' for n in nodes) > 1:
        raise ValueError('Use one rotor geometry and branch analysis nodes in this milestone')
    lookup = {node['id']: node for node in nodes}
    if len(lookup) != len(nodes):
        raise ValueError('Node IDs must be unique')
    inbound = {id: {} for id in lookup}
    dependencies = {id: set() for id in lookup}
    for node in nodes:
        if node['type'] not in REGISTRY:
            raise ValueError('Unregistered node type')
        config = node.get('config', {})
        if node['type'] in EXTERNAL_TYPES:
            if config:
                raise ValueError('External execution configuration belongs to the local integration')
        elif node['type'] == 'analysis':
            if config.get('model', 'bemt') not in ('bemt', 'llt', 'vlm', 'bem'):
                raise ValueError('Unknown aerodynamic solver')
            if set(config) - {'model', 'max_iterations', 'tolerance'}:
                raise ValueError('Unsupported analysis configuration')
            if type(config.get('max_iterations', 200)) is not int:
                raise ValueError('Iteration budget must be an integer')
            tolerance = config.get('tolerance', 1e-5)
            if type(tolerance) not in (int, float) or not math.isfinite(tolerance):
                raise ValueError('Tolerance must be a finite number')
            if not 1 <= config.get('max_iterations', 200) <= 10000 or not 0 < tolerance < 1:
                raise ValueError('Invalid numerical controls')
        elif node['type'] == 'sizing':
            if set(config) - {'mode', 'disk_loading'} or config.get('mode', 'manual') not in ('manual', 'actuator_disk'):
                raise ValueError('Invalid sizing mode')
            loading = config.get('disk_loading', 220)
            if type(loading) not in (int, float) or not math.isfinite(loading):
                raise ValueError('Disk loading must be a finite number')
            if config.get('mode') == 'actuator_disk' and not 1 < loading <= 5000:
                raise ValueError('Invalid disk loading')
        elif config:
            raise ValueError('This operation accepts no configuration')
    for edge in workflow.get('edges', []):
        source, target = edge['source'], edge['target']
        if source not in lookup or target not in lookup:
            raise ValueError('Connection references missing node')
        output = REGISTRY[lookup[source]['type']]['outputs'].get(edge['source_port'])
        input = REGISTRY[lookup[target]['type']]['inputs'].get(edge['target_port'])
        if not output or not input or not output.compatible(input):
            raise ValueError('Incompatible scientific ports')
        if edge['target_port'] in inbound[target]:
            raise ValueError('An input port accepts only one connection')
        inbound[target][edge['target_port']] = (source, edge['source_port'])
        dependencies[target].add(source)
    for id, node in lookup.items():
        if set(inbound[id]) != set(REGISTRY[node['type']]['inputs']):
            raise ValueError(f'Missing input at node {id}')
    order = []
    remaining = dict(dependencies)
    while remaining:
        ready = sorted(id for id, deps in remaining.items() if deps <= set(order))
        if not ready:
            raise ValueError('Workflow contains a cycle')
        order.extend(ready)
        for id in ready:
            del remaining[id]
    # Guided views represent the original topology, with documented parameters.
    standard = template()
    guided = ([{k: n[k] for k in ('id', 'type')} for n in nodes] ==
              [{k: n[k] for k in ('id', 'type')} for n in standard['nodes']] and
              workflow.get('edges') == standard['edges'])
    return {'valid': True, 'order': order, 'guided_compatible': guided, 'inbound': inbound}


class NumericalFailure(RuntimeError):
    def __init__(self, result):
        super().__init__('Aerodynamic solver did not converge; diagnostics retained')
        self.result = result


def execute(workflow, inputs, polar_asset, conditions=None, *, progress=None, cancelled=None, external_context=None):
    checked = validate(workflow)
    if any(n['type'] in EXTERNAL_TYPES for n in workflow['nodes']):
        if not external_context:
            raise ValueError('External workflow requires a configured integration and artifact root')
        from nova.application.external import execute_external
        values = {}
        output = None
        for id in checked['order']:
            if cancelled and cancelled():
                raise InterruptedError('Run cancelled')
            node = next(n for n in workflow['nodes'] if n['id'] == id)
            if node['type'].endswith('_input'):
                values[id] = {'case': copy.deepcopy(inputs)}
            else:
                if node['type'] != external_context['adapter_id']:
                    raise ValueError('Workflow and configured adapter differ')
                source, port = checked['inbound'][id]['case']
                output = execute_external({**external_context, 'workflow': workflow}, values[source][port], progress=progress, cancelled=cancelled)
                values[id] = {'result': output['data']}
        output['provenance']['workflow_hash'] = content_hash(workflow)
        return output
    conditions = conditions or {}
    if set(conditions) - {'air_density_kg_m3', 'air_viscosity_pa_s'}:
        raise ValueError('Only static axial operating conditions are supported')
    if polar_asset and polar_asset.get('airfoil') != inputs['airfoil']:
        raise ValueError('Polar asset and geometry airfoil differ')
    density = float(conditions.get('air_density_kg_m3', 1.225))
    viscosity = float(conditions.get('air_viscosity_pa_s', 1.81e-5))
    if not all(math.isfinite(v) and v > 0 for v in (density, viscosity, inputs['rpm'])):
        raise ValueError('Operating conditions must be finite and positive')
    values, results, logs = {}, [], []
    for index, id in enumerate(checked['order']):
        if cancelled and cancelled():
            raise InterruptedError('Run cancelled')
        node = next(n for n in workflow['nodes'] if n['id'] == id)
        args = {port: values[source][out] for port, (source, out) in checked['inbound'][id].items()}
        config, kind = node.get('config', {}), node['type']
        if kind == 'parameters':
            output = {'design': copy.deepcopy(inputs)}
        elif kind == 'sizing':
            design = copy.deepcopy(args['design'])
            if config.get('mode') == 'actuator_disk':
                design['diameter'] = math.sqrt(4 * design['thrust_target'] / (math.pi * config.get('disk_loading', 220)))
            output = {'design': design}
        elif kind == 'geometry':
            output = {'geometry': create_propeller_geometry(args['design'])}
        elif kind == 'analysis':
            from inverse_design import BEMTSolver, create_solver
            model = config.get('model', 'bemt')
            if model == 'bemt':
                if not polar_asset:
                    raise ValueError('Select a polar asset; synthetic data must be explicitly selected')
                provider = PolarProvider(polar_asset['points'], polar_asset['mach'], polar_asset['ncrit'])
                solver = BEMTSolver(air_density=density, air_viscosity=viscosity, polar_provider=provider,
                                    max_iterations=config.get('max_iterations', 200), tolerance=config.get('tolerance', 1e-5))
            else:
                solver = create_solver(model)
                solver.rho = density
                solver.viscosity = viscosity
                solver.axial_velocity = 0.
            result = run_propeller_analysis(model=model, geometry_data=args['geometry'], rpm=inputs['rpm'],
                                           target_thrust_n=inputs['thrust_target'], solver=solver)
            if model == 'bemt':
                result['warnings'].append('Polar policy: endpoint clipping; synthetic' if polar_asset.get('demonstration')
                                          else 'Polar policy: endpoint clipping; imported data')
                if provider.clipped:
                    result['warnings'].append('Polar samples clipped outside supplied alpha/Re coverage')
            else:
                result['warnings'].append('This approximation does not consume imported section polars')
            limits = args['geometry'].get('constraints', {})
            if limits.get('clipped_chord_stations') or limits.get('clipped_twist_stations'):
                result['warnings'].append(f"Geometry limits applied: {limits.get('clipped_chord_stations', 0)} chord and {limits.get('clipped_twist_stations', 0)} twist stations")
            result['node_id'] = id
            result['provenance'] = {'workflow_hash': content_hash(workflow), 'inputs_hash': content_hash(inputs),
                                    'polar_hash': (polar_asset.get('content_hash') or content_hash(polar_asset)) if polar_asset else None,
                                    'conditions': {'air_density_kg_m3': density, 'air_viscosity_pa_s': viscosity, 'axial_velocity_m_s': 0.},
                                    'geometry_hash': content_hash(args['geometry']),
                                    'solver_configuration': config,
                                    'polar_conditions': {'mach': polar_asset['mach'], 'ncrit': polar_asset['ncrit']} if polar_asset else None}
            result['quantities'] = {'figure_of_merit': result['performance']['efficiency'],
                                   'propulsive_efficiency': None}
            n, d = inputs['rpm'] / 60., args['geometry']['diameter_m']
            result['coefficients'] = {'CT': result['performance']['thrust_n'] / (density*n*n*d**4),
                                      'CP': result['performance']['power_w'] / (density*n**3*d**5),
                                      'CQ': result['performance']['torque_nm'] / (density*n*n*d**5)}
            results.append(result)
            if result.get('convergence') and not result['convergence']['converged']:
                raise NumericalFailure(result)
            output = {'result': result}
        else:
            output = args
        values[id] = output
        logs.append(f'{id}: completed')
        if progress:
            progress({'node': id, 'progress': (index + 1) / len(checked['order']), 'message': logs[-1]})
    geometry = next((v['geometry'] for v in values.values() if 'geometry' in v), None)
    return {'geometry': geometry, 'analyses': results, 'logs': logs, 'outputs': values, 'artifacts': {id + '.json': values[id]['result'] for id in values if next(n for n in workflow['nodes'] if n['id'] == id)['type'] == 'export'}}
