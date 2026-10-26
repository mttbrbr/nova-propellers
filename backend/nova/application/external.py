"""External scientific jobs and retained artifacts, independent of HTTP/UI."""
import csv
import io
from pathlib import Path

from nova.adapters.base import AdapterConfiguration, execute_adapter
from nova.adapters.registry import get
from nova.core.data import canonical_json, content_hash


def configuration(document):
    return AdapterConfiguration(Path(document['executable']), document['environment_kind'], document.get('options', {}))


def validate_job(job, inputs):
    adapter = get(job['adapter_id'])
    adapter.validate(inputs, configuration(job['configuration']))
    return adapter


def execute_external(job, inputs, *, progress=None, cancelled=None):
    adapter = validate_job(job, inputs)
    def log(message):
        if progress:
            progress({'progress': .5, 'message': message[-2000:]})
    output = execute_adapter(adapter, configuration(job['configuration']), inputs, job['artifact_root'],
                             on_log=log, cancelled=cancelled)
    if job.get('workflow'):
        directory = Path(output['working_directory'])
        (directory / 'workflow.json').write_text(canonical_json(job['workflow']))
        output['provenance']['workflow_hash'] = content_hash(job['workflow'])
        (directory / 'execution.json').write_text(canonical_json(output['provenance']))
        output['artifacts'].append('workflow.json')
    return {'kind': 'external', 'schema_version': 1, 'adapter_id': job['adapter_id'], **output}


def failure_artifacts(exception, job):
    """Publish only files inside this run's private artifact root."""
    directory = Path(getattr(exception, 'working_directory', job['artifact_root'])).resolve()
    root = Path(job['artifact_root']).resolve()
    if not directory.is_relative_to(root) or not directory.is_dir():
        return None
    artifacts = [str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file() and not p.is_symlink()]
    return {'kind': 'external', 'schema_version': 1, 'adapter_id': job['adapter_id'], 'data': None,
            'provenance': {'state': 'cancelled' if isinstance(exception, InterruptedError) or getattr(exception, 'cancelled', False) else 'failed', 'error': str(exception)},
            'working_directory': str(directory), 'artifacts': sorted(artifacts)}


def result_csv(data):
    output = io.StringIO()
    writer = csv.writer(output)
    if data['kind'] == 'time_series_result':
        writer.writerow(['Time [s]', *[f"{c['name']} [{c['units'].strip('()')}]" for c in data['channels']]])
        for time, values in zip(data['time_s'], data['values'], strict=True):
            writer.writerow([time, *values])
    elif data['kind'] == 'wind_farm_result':
        writer.writerow(['turbine', 'x_m', 'y_m', 'direction_deg', 'wind_speed_m_s', 'joint_probability',
                         'effective_speed_m_s', 'power_W', 'power_without_wakes_W', 'turbine_AEP_GWh', 'turbine_AEP_without_wakes_GWh'])
        for i, (x, y) in enumerate(zip(data['layout']['x_m'], data['layout']['y_m'], strict=True)):
            for d, direction in enumerate(data['directions_deg']):
                for s, speed in enumerate(data['speeds_m_s']):
                    writer.writerow([i, x, y, direction, speed, data['probabilities'][d][s],
                                     data['effective_speed_m_s'][i][d][s], data['power_w'][i][d][s],
                                     data['power_without_wakes_w'][i][d][s], data['aep_gwh'][i], data['aep_without_wakes_gwh'][i]])
    else:
        raise ValueError('Unsupported external result type')
    return output.getvalue()
