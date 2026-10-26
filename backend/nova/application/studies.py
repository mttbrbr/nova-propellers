"""Bounded one/two-axis studies through the existing workflow engine."""
import copy
import math
from itertools import product
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nova.application.geometry import create_propeller_geometry
from nova.core.data import content_hash
from nova.core.design import GeometryRequest
from nova.workflow.engine import NumericalFailure, execute, validate

PARAMETERS = {
    'rpm': {'label': 'Rotation speed', 'units': 'rpm', 'location': 'inputs'},
    'diameter': {'label': 'Rotor diameter (geometry controls fixed)', 'units': 'm', 'location': 'inputs'},
    'air_density_kg_m3': {'label': 'Air density', 'units': 'kg/m^3', 'location': 'conditions'},
    'air_viscosity_pa_s': {'label': 'Dynamic viscosity', 'units': 'Pa*s', 'location': 'conditions'},
}


class StudyAxis(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    parameter: Literal['rpm', 'diameter', 'air_density_kg_m3', 'air_viscosity_pa_s']
    values: list[float] = Field(min_length=2, max_length=32)

    @field_validator('values', mode='before')
    @classmethod
    def numeric_values(cls, values):
        if not isinstance(values, list) or any(type(v) not in (int, float) for v in values):
            raise ValueError('Study values must be numeric, not strings or booleans')
        return values

    @field_validator('values')
    @classmethod
    def distinct_values(cls, values):
        if len(set(values)) != len(values) or any(v <= 0 for v in values):
            raise ValueError('Use distinct positive study values')
        return values


class StudyDefinition(StudyAxis):
    secondary: StudyAxis | None = None

    @model_validator(mode='after')
    def bounded_distinct_axes(self):
        if self.secondary:
            if self.parameter == self.secondary.parameter:
                raise ValueError('Primary and secondary study axes must be distinct')
            if len(self.values) * len(self.secondary.values) > 32:
                raise ValueError('A Cartesian study permits at most 32 cases')
        return self

def scientific_inputs(inputs):
    normalized = copy.deepcopy(inputs)
    for assignment in normalized.get('airfoil_assignments', []):
        assignment.pop('asset_id', None)
    return normalized


def build_cases(snapshot, definition):
    definition = StudyDefinition.model_validate(definition)
    validate(snapshot['workflow'])
    if not any(n['type'] == 'analysis' for n in snapshot['workflow']['nodes']):
        raise ValueError('A study requires an aerodynamic analysis node')
    parameters = {definition.parameter}
    if definition.secondary:
        parameters.add(definition.secondary.parameter)
    if 'air_viscosity_pa_s' in parameters and not any(
            n['type'] == 'analysis' and n.get('config', {}).get('model', 'bemt') == 'bemt'
            for n in snapshot['workflow']['nodes']):
        raise ValueError('A viscosity sweep requires BEMT; the other native models do not use viscosity')
    if 'diameter' in parameters and any(n['type'] == 'sizing' and n.get('config', {}).get('mode') == 'actuator_disk'
                                                for n in snapshot['workflow']['nodes']):
        raise ValueError('Use manual sizing for a diameter sweep; ideal sizing would overwrite its values')
    analysis_count = sum(n['type'] == 'analysis' for n in snapshot['workflow']['nodes'])
    total_cases = len(definition.values) * (len(definition.secondary.values) if definition.secondary else 1)
    if analysis_count * total_cases > 128:
        raise ValueError('A study permits at most 128 analysis evaluations')
    baseline_inputs = GeometryRequest.model_validate(snapshot['inputs']).model_dump()
    baseline_inputs['geometry_parameters'] = copy.deepcopy(create_propeller_geometry(baseline_inputs)['parameters'])
    cases = []
    secondary_values = definition.secondary.values if definition.secondary else [None]
    for index, (value, secondary_value) in enumerate(product(definition.values, secondary_values)):
        inputs = copy.deepcopy(baseline_inputs)
        conditions = copy.deepcopy(snapshot.get('conditions', {}))
        destination = inputs if PARAMETERS[definition.parameter]['location'] == 'inputs' else conditions
        destination[definition.parameter] = value
        if definition.secondary:
            destination = inputs if PARAMETERS[definition.secondary.parameter]['location'] == 'inputs' else conditions
            destination[definition.secondary.parameter] = secondary_value
        inputs = GeometryRequest.model_validate(inputs).model_dump()
        if set(conditions) - {'air_density_kg_m3', 'air_viscosity_pa_s'} or any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in conditions.values()):
            raise ValueError('Invalid static operating conditions')
        cases.append({'index': index, 'value': value, 'inputs': inputs, 'conditions': conditions,
                      'input_hash': content_hash({'inputs': scientific_inputs(inputs), 'conditions': conditions,
                                                  'workflow': snapshot['workflow'], 'polar_hash': (snapshot.get('polar_asset') or {}).get('content_hash')})})
        if definition.secondary:
            cases[-1].update(secondary_value=secondary_value, secondary_parameter=definition.secondary.parameter,
                             secondary_units=PARAMETERS[definition.secondary.parameter]['units'])
    return cases


def execute_study(snapshot, definition, *, progress=None, checkpoint=None, cancelled=None):
    snapshot = copy.deepcopy(snapshot)
    definition = StudyDefinition.model_validate(definition)
    cases = build_cases(snapshot, definition.model_dump(exclude_none=True))
    completed = []
    result = {'kind': 'study', 'schema_version': 1, 'definition': definition.model_dump(exclude_none=True),
              'units': PARAMETERS[definition.parameter]['units'], 'cases': completed,
              'total_cases': len(cases), 'completed_cases': 0, 'failed_cases': 0, 'study_status': 'running'}
    if definition.secondary:
        result['secondary_units'] = PARAMETERS[definition.secondary.parameter]['units']
    for case in cases:
        if cancelled and cancelled():
            raise InterruptedError('Study cancelled')
        def report(event):
            if progress:
                progress({**event, 'progress': (case['index'] + event['progress']) / len(cases),
                          'message': f"Case {case['index'] + 1}/{len(cases)}: {event['message']}"})
        try:
            output = execute(snapshot['workflow'], case['inputs'], snapshot.get('polar_asset'),
                             case['conditions'], progress=report, cancelled=cancelled)
            output.pop('outputs', None)  # Avoid repeating every node payload in each study case.
            completed.append({**case, 'state': 'succeeded', 'result': output})
        except InterruptedError:
            raise
        except NumericalFailure as exc:
            completed.append({**case, 'state': 'failed', 'error': str(exc), 'diagnostics': exc.result})
        except (ValueError, RuntimeError, FloatingPointError, ArithmeticError) as exc:
            completed.append({**case, 'state': 'failed', 'error': str(exc)})
        result['completed_cases'] = len(completed)
        result['failed_cases'] = sum(item['state'] == 'failed' for item in completed)
        if checkpoint:
            checkpoint(copy.deepcopy(result))
        if progress:
            progress({'progress': len(completed) / len(cases), 'message': f"Case {case['index'] + 1}: {completed[-1]['state']}"})
    result['study_status'] = ('failed' if result['failed_cases'] == len(cases) else
                              'completed_with_failures' if result['failed_cases'] else 'succeeded')
    return result


def comparison_rows(record):
    """Expose only successful static native results with their own conditions."""
    if record.get('external_job'):
        raise ValueError('External time series and wind farm results are not static rotor performance results')
    output = record.get('result') or {}
    if output.get('kind') == 'comparison':
        from nova.application.comparisons import comparison_rows as batch_rows
        return batch_rows(record)
    if output.get('kind') == 'study':
        cases = output['cases']
    else:
        cases = [{'index': None, 'value': None, 'state': record['state'], 'inputs': record['inputs'],
                  'conditions': record.get('conditions', {}), 'result': output, 'error': record.get('error')}]
    rows = []
    for case in cases:
        secondary = {key: case[key] for key in ('secondary_parameter', 'secondary_units', 'secondary_value') if key in case}
        results = (case.get('result') or {}).get('analyses', []) if case['state'] == 'succeeded' else []
        if not results:
            rows.append({'run_id': record['id'], 'case_index': case['index'], 'value': case['value'], 'parameter': (record.get('study') or {}).get('parameter'),
                         'parameter_units': output.get('units'), 'state': case['state'], 'run_state': record['state'], 'error': case.get('error') or 'No successful analysis result', **secondary})
        for analysis in results:
            if analysis['units'] != {'thrust': 'N', 'torque': 'N*m', 'power': 'W', 'efficiency': 'dimensionless'}:
                raise ValueError('Comparison requires matching native scientific units')
            if analysis['operating_point']['axial_velocity_m_s'] != 0:
                raise ValueError('Comparison currently supports static axial runs only')
            rows.append({'run_id': record['id'], 'case_index': case['index'], 'value': case['value'],
                         'parameter': (record.get('study') or {}).get('parameter'), 'parameter_units': output.get('units'),
                         'state': 'succeeded', 'run_state': record['state'], 'airfoil': case['inputs']['airfoil'],
                         'viscosity_pa_s': case.get('conditions', {}).get('air_viscosity_pa_s', 1.81e-5), 'node_id': analysis.get('node_id'), 'model': analysis['model'],
                         'fidelity': analysis['fidelity'],
                         'polar_data': ((record.get('polar_asset') or {}).get('filename', 'unavailable') if analysis['model'] == 'bemt' else 'analytic approximation; polars unused'), 'rpm': analysis['operating_point']['rpm'],
                         'density_kg_m3': analysis['operating_point']['air_density_kg_m3'],
                         'diameter_m': (case.get('result') or {}).get('geometry', {}).get('diameter_m'),
                         'thrust_n': analysis['performance']['thrust_n'], 'torque_nm': analysis['performance']['torque_nm'],
                         'power_w': analysis['performance']['power_w'],
                         'figure_of_merit': analysis['performance']['efficiency'], **secondary})
    return rows


def validate_study_result(result, snapshot):
    """Validate archived checkpoints/completed studies without re-executing them."""
    from inverse_design import GeometryData
    from nova.core.contracts import CanonicalSolverResult
    expected = build_cases(snapshot, result['definition'])
    if result.get('kind') != 'study' or result.get('schema_version') != 1:
        raise ValueError('Unsupported study result schema')
    if snapshot.get('study') and StudyDefinition.model_validate(snapshot['study']).model_dump(exclude_none=True) != result['definition']:
        raise ValueError('Study definition differs from its frozen run')
    count = len(result['cases'])
    failures = sum(case.get('state') == 'failed' for case in result['cases'])
    if any(type(result.get(key)) is not int for key in ('total_cases', 'completed_cases', 'failed_cases')):
        raise ValueError('Study counters must be integers')
    if result['total_cases'] != len(expected) or result['completed_cases'] != count or result['failed_cases'] != failures:
        raise ValueError('Study counters disagree with its cases')
    if result.get('units') != PARAMETERS[result['definition']['parameter']]['units']:
        raise ValueError('Study parameter units differ from its definition')
    secondary = result['definition'].get('secondary')
    if result.get('secondary_units') != (PARAMETERS[secondary['parameter']]['units'] if secondary else None):
        raise ValueError('Secondary study units differ from its definition')
    status = result.get('study_status')
    if status not in ('succeeded', 'completed_with_failures', 'failed', 'cancelled', 'interrupted'):
        raise ValueError('Invalid archived study status')
    if status in ('succeeded', 'completed_with_failures', 'failed'):
        if count != len(expected):
            raise ValueError('A completed study requires all declared cases')
        expected_status = 'failed' if failures == count else 'completed_with_failures' if failures else 'succeeded'
        if status != expected_status:
            raise ValueError('Study status disagrees with case outcomes')
    if snapshot.get('state') == 'succeeded' and status not in ('succeeded', 'completed_with_failures'):
        raise ValueError('Successful run contains an incomplete study')
    if len(result['cases']) > len(expected):
        raise ValueError('Study has more cases than its definition')
    for case, planned in zip(result['cases'], expected):
        if scientific_inputs(case['inputs']) != scientific_inputs(planned['inputs']) or any(case.get(key) != planned[key] for key in ('index', 'value', 'conditions', 'input_hash')) or any(case.get(key) != planned.get(key) for key in ('secondary_parameter', 'secondary_value', 'secondary_units')):
            raise ValueError('Study case does not match its frozen configuration')
        if case['state'] not in ('succeeded', 'failed'):
            raise ValueError('Invalid study case state')
        analyses = []
        if case['state'] == 'succeeded':
            GeometryData.from_dict(case['result']['geometry'])
            analyses = case['result']['analyses']
            expected_nodes = {n['id']: n.get('config', {}).get('model', 'bemt') for n in snapshot['workflow']['nodes'] if n['type'] == 'analysis'}
            if len(analyses) != len(expected_nodes) or {a.get('node_id') for a in analyses} != set(expected_nodes):
                raise ValueError('Study case is missing its declared analysis outputs')
            if any(a['model'] != expected_nodes[a['node_id']] for a in analyses):
                raise ValueError('Study result model differs from its workflow node')
        elif case.get('diagnostics'):
            analyses = [case['diagnostics']]
        for analysis in analyses:
            if case['state'] == 'succeeded' and analysis.get('convergence') and not analysis['convergence']['converged']:
                raise ValueError('Unconverged analysis cannot be a successful study case')
            CanonicalSolverResult.model_validate({k: v for k, v in analysis.items() if k in CanonicalSolverResult.model_fields})
