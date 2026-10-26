"""Isolated worker protocol, also invoked by the frozen desktop launcher."""
import json
import signal
import sys

from nova.workflow.engine import NumericalFailure, execute


class WorkerCancelled(Exception):
    # selectors intentionally catches InterruptedError as a retryable OS signal.
    # A distinct exception must unwind its polling loop and child-process cleanup.
    cancelled = True


def main():
    def emit(value):
        print(json.dumps(value, allow_nan=False), flush=True)
    def cancel(_signal, _frame):
        raise WorkerCancelled('Run cancelled')
    signal.signal(signal.SIGTERM, cancel)
    try:
        request = json.load(sys.stdin)
        if request.get('external_job'):
            result = execute(request['workflow'], request['inputs'], None,
                             external_context=request['external_job'], progress=lambda event: emit({'event': event}))
        elif request.get('comparison'):
            from nova.application.comparisons import execute_comparison
            result = execute_comparison(request, progress=lambda event: emit({'event': event}),
                                        checkpoint=lambda value: emit({'checkpoint': value}))
        elif request.get('optimization'):
            from inverse_design import BEMTSolver, create_solver
            from nova.application.optimization import run_inverse_design
            from nova.core.polars import PolarProvider
            settings = request['optimization']
            if settings['solver'] == 'bemt':
                asset = request['polar_asset']
                solver = BEMTSolver(polar_provider=PolarProvider(asset['points'], asset['mach'], asset['ncrit']))
            else:
                solver = create_solver(settings['solver'])
                solver.axial_velocity = 0.
            solver.rho = request.get('conditions', {}).get('air_density_kg_m3', 1.225)
            solver.viscosity = request.get('conditions', {}).get('air_viscosity_pa_s', 1.81e-5)
            result = {'kind': 'optimization', 'candidate': run_inverse_design(settings, solver=solver, design_inputs=request['inputs'],
                      progress=lambda count, loss: emit({'event': {'progress': min(.95, count / settings['max_iterations']),
                                                                  'message': f'Evaluation {count}: loss {loss:.6g}'}}))}
        elif request.get('study'):
            from nova.application.studies import execute_study
            result = execute_study(request, request['study'],
                                   progress=lambda event: emit({'event': event}),
                                   checkpoint=lambda value: emit({'checkpoint': value}))
        else:
            result = execute(request['workflow'], request['inputs'], request.get('polar_asset'),
                             request.get('conditions'), progress=lambda event: emit({'event': event}))
        emit({'result': result})
        if result.get('study_status') == 'failed' or result.get('comparison_status') == 'failed':
            emit({'error': 'All cases failed; diagnostics retained'})
            return 1
        return 0
    except NumericalFailure as exc:
        emit({'error': str(exc), 'diagnostics': exc.result})
    except Exception as exc:
        if 'request' in locals() and request.get('external_job'):
            from nova.application.external import failure_artifacts
            artifacts = failure_artifacts(exc, request['external_job'])
            if artifacts:
                emit({'result': artifacts})
        emit({'error': str(exc)})
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
