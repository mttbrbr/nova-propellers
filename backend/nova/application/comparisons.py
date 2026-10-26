"""Strict solver comparisons over frozen saved native configurations."""
import copy

from nova.application.geometry import create_propeller_geometry
from nova.core.data import content_hash
from nova.core.polars import FIELDS, PolarProvider
from nova.workflow.engine import NumericalFailure, execute, validate

METRICS = ('thrust_n', 'torque_nm', 'power_w', 'figure_of_merit')


def shape_hash(inputs):
    geometry = create_propeller_geometry(inputs)
    return content_hash({key: geometry[key] for key in ('diameter_m', 'blades', 'propeller_type', 'stations')})


def conditions(snapshot):
    return {'rpm': snapshot['inputs']['rpm'], 'target_thrust_n': snapshot['inputs']['thrust_target'],
            'air_density_kg_m3': snapshot.get('conditions', {}).get('air_density_kg_m3', 1.225),
            'air_viscosity_pa_s': snapshot.get('conditions', {}).get('air_viscosity_pa_s', 1.81e-5)}


def fingerprint(snapshot):
    return content_hash({'shape': shape_hash(snapshot['inputs']), 'conditions': conditions(snapshot),
                         'workflow': snapshot['workflow'], 'name': snapshot['name'], 'revision': snapshot['revision'],
                         'polar_hash': (snapshot.get('polar_asset') or {}).get('content_hash')})


def scientific_polar_hash(asset):
    """Compare coefficients and conditions independently of import provenance.

    The original asset content hash remains in frozen execution fingerprints.
    """
    points = sorted(tuple(float(point[field]) for field in FIELDS) for point in asset['points'])
    return content_hash({'airfoil': asset['airfoil'], 'mach': float(asset['mach']),
                         'ncrit': float(asset['ncrit']), 'points': points})


def validate_comparison(comparison):
    snapshots = comparison['simulations']
    if not isinstance(snapshots, list) or not 2 <= len(snapshots) <= 8:
        raise ValueError('A solver comparison requires 2–8 saved simulations')
    if len({s['id'] for s in snapshots}) != len(snapshots):
        raise ValueError('Select distinct saved simulations')
    baseline_shape = shape_hash(snapshots[0]['inputs'])
    baseline_conditions = conditions(snapshots[0])
    summaries, warnings, polar_hashes = [], [], set()
    for snapshot in snapshots:
        checked = validate(snapshot['workflow'])
        analyses = [n for n in snapshot['workflow']['nodes'] if n['type'] == 'analysis']
        if not checked['guided_compatible'] or len(analyses) != 1:
            raise ValueError('Strict comparisons currently require one analysis in the guided native workflow')
        if any(n['type'] == 'sizing' and n.get('config', {}).get('mode') == 'actuator_disk' for n in snapshot['workflow']['nodes']):
            raise ValueError('Materialize automatic sizing and use manual geometry before comparing solvers')
        if shape_hash(snapshot['inputs']) != baseline_shape:
            raise ValueError('Solver comparisons require identical evaluated baseline geometry')
        if conditions(snapshot) != baseline_conditions:
            raise ValueError('Solver comparisons require matching RPM, target thrust, density and viscosity')
        model = analyses[0].get('config', {}).get('model', 'bemt')
        asset = snapshot.get('polar_asset')
        if model == 'bemt':
            if not asset or asset['airfoil'] != snapshot['inputs']['airfoil']:
                raise ValueError('BEMT requires a matching frozen polar asset')
            PolarProvider(asset['points'], asset['mach'], asset['ncrit'])
            polar_hashes.add(scientific_polar_hash(asset))
        else:
            warnings.append(f"{snapshot['name']}: {model} uses an analytic approximation; imported polars are not consumed")
        summaries.append({'id': snapshot['id'], 'name': snapshot['name'], 'revision': snapshot['revision'],
                          'geometry_id': snapshot.get('geometry_id'), 'geometry_revision': snapshot.get('geometry_revision'),
                          'models': [{'node_id': analyses[0]['id'], 'model': model}],
                          'polar_asset_id': snapshot.get('polar_asset_id'),
                          'polar_data': (asset or {}).get('filename', 'unavailable') if model == 'bemt' else 'analytic approximation; polars unused'})
    if len(polar_hashes) > 1:
        raise ValueError('BEMT comparisons require the same scientific polar data')
    return {'valid': True, 'name': comparison['name'], 'simulations': summaries, 'warnings': warnings,
            'baseline_simulation_id': snapshots[0]['id'], 'geometry_hash': baseline_shape,
            'operating_conditions': baseline_conditions}


def comparison_rows(record):
    from nova.application.studies import comparison_rows as native_rows
    result = record.get('result') or {}
    cases = result.get('cases', [])
    rows = []
    for case in cases:
        snapshot = case['snapshot']
        source = {**snapshot, 'id': record.get('id'), 'state': case['state'],
                  'result': case.get('result'), 'error': case.get('error')}
        native = native_rows(source)
        for row in native:
            analysis = ((case.get('result') or {}).get('analyses') or [{}])[0]
            row.update(case_index=case['index'], simulation_id=case['simulation_id'], simulation_name=case['simulation_name'],
                       simulation_revision=case['simulation_revision'], run_state=record.get('state'),
                       geometry_id=snapshot.get('geometry_id'), geometry_revision=snapshot.get('geometry_revision'),
                       converged=(analysis.get('convergence') or {}).get('converged'))
            rows.append(row)
    baseline = rows[0] if rows and cases[0]['state'] == 'succeeded' else None
    for row in rows:
        differences, reasons = {}, {}
        for key in METRICS:
            reason = 'baseline_failed' if baseline is None else 'case_failed' if row['state'] != 'succeeded' else 'zero_baseline' if baseline.get(key) == 0 else None
            differences[key] = None if reason else 100 * (row[key] - baseline[key]) / abs(baseline[key])
            reasons[key] = reason
        row.update(baseline_simulation_id=record['comparison']['simulations'][0]['id'],
                   baseline_differences_pct=differences, baseline_difference_reasons=reasons)
    return rows


def execute_comparison(snapshot, *, progress=None, checkpoint=None, cancelled=None):
    comparison = copy.deepcopy(snapshot['comparison'])
    validate_comparison(comparison)
    result = {'kind': 'comparison', 'schema_version': 1, 'cases': [], 'total_cases': len(comparison['simulations']),
              'completed_cases': 0, 'failed_cases': 0, 'comparison_status': 'running',
              'baseline_simulation_id': comparison['simulations'][0]['id'], 'rows': []}
    for index, config in enumerate(comparison['simulations']):
        if cancelled and cancelled():
            raise InterruptedError('Comparison cancelled')
        case = {'index': index, 'simulation_id': config['id'], 'simulation_name': config['name'],
                'simulation_revision': config['revision'], 'snapshot': config, 'input_hash': fingerprint(config)}
        def report(event):
            if progress:
                progress({**event, 'progress': (index + event['progress']) / result['total_cases'],
                          'message': f"{config['name']}: {event['message']}"})
        try:
            output = execute(config['workflow'], config['inputs'], config.get('polar_asset'), config.get('conditions'),
                             progress=report, cancelled=cancelled)
            output.pop('outputs', None)
            case.update(state='succeeded', result=output)
        except InterruptedError:
            raise
        except NumericalFailure as exc:
            case.update(state='failed', error=str(exc), diagnostics=exc.result)
        except (ValueError, RuntimeError, ArithmeticError) as exc:
            case.update(state='failed', error=str(exc))
        result['cases'].append(case)
        result.update(completed_cases=len(result['cases']), failed_cases=sum(c['state'] == 'failed' for c in result['cases']))
        result['rows'] = comparison_rows({**snapshot, 'result': result})
        if checkpoint:
            checkpoint(copy.deepcopy(result))
    result['comparison_status'] = 'failed' if result['failed_cases'] == result['total_cases'] else 'completed_with_failures' if result['failed_cases'] else 'succeeded'
    result['rows'] = comparison_rows({**snapshot, 'state': 'failed' if result['comparison_status'] == 'failed' else 'succeeded', 'result': result})
    return result


def validate_result(result, record):
    from inverse_design import GeometryData

    from nova.core.contracts import CanonicalSolverResult
    validate_comparison(record['comparison'])
    configs = record['comparison']['simulations']
    cases = result['cases']
    if any(type(result.get(k)) is not int for k in ('total_cases', 'completed_cases', 'failed_cases')) or result.get('schema_version') != 1 or result.get('total_cases') != len(configs) or result.get('completed_cases') != len(cases) or len(cases) > len(configs):
        raise ValueError('Invalid comparison counters')
    failures = sum(c['state'] == 'failed' for c in cases)
    if result.get('failed_cases') != failures or result.get('baseline_simulation_id') != configs[0]['id']:
        raise ValueError('Invalid comparison failure count or baseline')
    status = result.get('comparison_status')
    if status not in ('succeeded', 'completed_with_failures', 'failed', 'cancelled', 'interrupted'):
        raise ValueError('Invalid comparison status')
    if status in ('succeeded', 'completed_with_failures', 'failed'):
        expected = 'failed' if failures == len(configs) else 'completed_with_failures' if failures else 'succeeded'
        if len(cases) != len(configs) or status != expected:
            raise ValueError('Incomplete comparison or inconsistent outcomes')
    if record.get('state') == 'succeeded' and status not in ('succeeded', 'completed_with_failures'):
        raise ValueError('Successful run has incomplete comparison')
    for index, case in enumerate(cases):
        config = configs[index]
        if case['index'] != index or case['simulation_id'] != config['id'] or case['simulation_name'] != config['name'] or case['simulation_revision'] != config['revision'] or case['snapshot'] != config or case['input_hash'] != fingerprint(config):
            raise ValueError('Comparison case differs from frozen source')
        if case['state'] == 'succeeded':
            output = case['result']
            GeometryData.from_dict(output['geometry'])
            if shape_hash(config['inputs']) != content_hash({key: output['geometry'][key] for key in ('diameter_m', 'blades', 'propeller_type', 'stations')}):
                raise ValueError('Comparison output geometry differs')
            if len(output['analyses']) != 1:
                raise ValueError('Comparison analysis outputs differ')
            analysis = output['analyses'][0]
            declared = next(n for n in config['workflow']['nodes'] if n['type'] == 'analysis')
            if analysis['model'] != declared.get('config', {}).get('model', 'bemt') or analysis.get('node_id') != declared['id'] or analysis.get('convergence') and not analysis['convergence']['converged']:
                raise ValueError('Comparison analysis model or convergence differs')
            point = analysis['operating_point']
            if point['rpm'] != config['inputs']['rpm'] or point['air_density_kg_m3'] != conditions(config)['air_density_kg_m3'] or point['axial_velocity_m_s'] != 0:
                raise ValueError('Comparison result operating conditions differ')
            CanonicalSolverResult.model_validate({k: v for k, v in analysis.items() if k in CanonicalSolverResult.model_fields})
        elif case['state'] != 'failed':
            raise ValueError('Invalid comparison case state')
        elif case.get('diagnostics'):
            CanonicalSolverResult.model_validate({k: v for k, v in case['diagnostics'].items() if k in CanonicalSolverResult.model_fields})
    if result.get('rows') != comparison_rows({**record, 'result': result}):
        raise ValueError('Comparison rows differ from retained results')
