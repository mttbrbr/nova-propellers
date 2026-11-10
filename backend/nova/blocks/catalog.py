"""Block catalogue for constraint-driven engineering workflows.

Blocks are split in two families:

* general  – domain-free building blocks: parameters with limits, expressions,
             merges, constraints, sweeps, filters, selection, optimisation and
             reports. They operate on named quantities, so they work for any
             rotor and any future solver.
* specific – rotor engineering: rotor definitions (HAWT, VAWT, propeller,
             marine), operating conditions, correction models, solvers,
             performance curves (Cp–λ, K_T–J), marine conditions and domain
             design checks.

Port types: record (named scalars), rotor_spec, rotor_result, table,
report. A ``record`` is the universal currency between general blocks.
"""
import copy

from nova.physics.rotors import DEFAULTS

TYPES = ('record', 'rotor_spec', 'rotor_result', 'table', 'report')


def port(name, kind, optional=False, label=None):
    return {'name': name, 'type': kind, 'optional': optional, 'label': label or name}


def _rotor_defaults(kind):
    d = copy.deepcopy(DEFAULTS[kind])
    return {'geometry': d['geometry'], 'section': d['section'], 'bindings': {}}


BLOCKS = {
    # ------------------------------------------------------------ general
    'parameter': dict(
        family='general', category='Inputs', label='Parameter',
        description='Named value with engineering limits; the run fails if the value leaves its range.',
        inputs=[], outputs=[port('value', 'record')],
        defaults={'name': 'x', 'value': 1.0, 'unit': '', 'min': None, 'max': None}),
    'parameter_set': dict(
        family='general', category='Inputs', label='Parameter set',
        description='Several named values with optional limits, emitted as one record.',
        inputs=[], outputs=[port('values', 'record')],
        defaults={'values': [{'name': 'radius_m', 'value': 5.0, 'unit': 'm', 'min': 1.0, 'max': 60.0}]}),
    'expression': dict(
        family='general', category='Logic', label='Expression',
        description='Derive new quantities from a record (e.g. P_kW = power_w / 1000).',
        inputs=[port('values', 'record')], outputs=[port('values', 'record')],
        defaults={'assignments': [{'name': 'power_kw', 'expression': 'power_w / 1000', 'unit': 'kW'}]}),
    'merge': dict(
        family='general', category='Logic', label='Merge',
        description='Combine two records; the second wins on name clashes.',
        inputs=[port('a', 'record'), port('b', 'record')], outputs=[port('values', 'record')], defaults={}),
    'constraint': dict(
        family='general', category='Constraints', label='Constraints',
        description='Check any expression against limits. Hard violations make the design infeasible; '
                    '“stop” blocks every downstream block.',
        inputs=[port('values', 'record')], outputs=[port('values', 'record'), port('report', 'report')],
        defaults={'checks': [{'quantity': 'power_w', 'operator': '>=', 'value': 1000, 'severity': 'hard', 'label': 'Minimum power', 'unit': 'W'}],
                  'on_violation': 'report'}),
    'sweep': dict(
        family='general', category='Studies', label='Sweep',
        description='Vary one specification field over a list or range and tabulate every output.',
        inputs=[port('spec', 'rotor_spec')], outputs=[port('table', 'table')],
        defaults={'path': 'geometry.radius_m', 'start': 3.0, 'stop': 8.0, 'count': 6, 'values': None, 'checks': []}),
    'filter': dict(
        family='general', category='Studies', label='Feasible filter',
        description='Keep the table rows that satisfy the constraints.',
        inputs=[port('table', 'table')], outputs=[port('table', 'table')],
        defaults={'checks': []}),
    'select': dict(
        family='general', category='Studies', label='Select best',
        description='Pick the row that maximises or minimises an expression.',
        inputs=[port('table', 'table')], outputs=[port('values', 'record')],
        defaults={'objective': 'CP', 'sense': 'maximize', 'feasible_only': True}),
    'optimizer': dict(
        family='general', category='Studies', label='Optimizer',
        description='Constrained optimisation of specification fields (grid, Nelder–Mead with penalty, COBYLA).',
        inputs=[port('spec', 'rotor_spec')],
        outputs=[port('spec', 'rotor_spec'), port('values', 'record'), port('history', 'table')],
        defaults={'variables': [{'path': 'geometry.design_tsr', 'min': 4.0, 'max': 10.0}],
                  'objective': 'CP', 'sense': 'maximize', 'checks': [], 'method': 'cobyla',
                  'max_evaluations': 80, 'grid_levels': 5}),
    'report': dict(
        family='general', category='Outputs', label='Report',
        description='Collect values, tables and constraint reports into the run summary.',
        inputs=[port('a', 'record', True), port('b', 'table', True), port('c', 'report', True), port('d', 'report', True)],
        outputs=[port('report', 'report')], defaults={'title': 'Design summary'}),

    # ------------------------------------------------------------ specific
    'rotor_hawt': dict(
        family='specific', category='Rotors', label='HAWT rotor',
        description='Horizontal-axis wind/tidal rotor: optimum (Burton) or explicit blade.',
        inputs=[port('parameters', 'record', True)], outputs=[port('spec', 'rotor_spec')],
        defaults=_rotor_defaults('hawt')),
    'rotor_vawt': dict(
        family='specific', category='Rotors', label='VAWT rotor',
        description='Darrieus / H-rotor: blades, radius, height, chord, shape, struts and shaft.',
        inputs=[port('parameters', 'record', True)], outputs=[port('spec', 'rotor_spec')],
        defaults=_rotor_defaults('vawt')),
    'rotor_propeller': dict(
        family='specific', category='Rotors', label='Air propeller',
        description='Propeller blade from pitch ratio and chord distribution.',
        inputs=[port('parameters', 'record', True)], outputs=[port('spec', 'rotor_spec')],
        defaults=_rotor_defaults('propeller')),
    'rotor_marine': dict(
        family='specific', category='Rotors', label='Marine propeller',
        description='Wageningen B-series outline from Z, A_E/A_0 and P/D.',
        inputs=[port('parameters', 'record', True)], outputs=[port('spec', 'rotor_spec')],
        defaults=_rotor_defaults('marine')),
    'operating_point': dict(
        family='specific', category='Conditions', label='Operating point',
        description='Fluid (air, fresh or sea water) and velocity with rpm, tip-speed ratio or advance ratio.',
        inputs=[port('spec', 'rotor_spec'), port('parameters', 'record', True)], outputs=[port('spec', 'rotor_spec')],
        defaults={'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 6.0}, 'bindings': {}}),
    'marine_conditions': dict(
        family='specific', category='Conditions', label='Hull & immersion',
        description='Wake fraction, thrust deduction, relative rotative efficiency and shaft immersion.',
        inputs=[port('spec', 'rotor_spec')], outputs=[port('spec', 'rotor_spec')],
        defaults=copy.deepcopy(DEFAULTS['marine']['marine'])),
    'corrections_axial': dict(
        family='specific', category='Corrections', label='Axial corrections',
        description='Tip loss, hub loss, high induction, rotational augmentation, compressibility.',
        inputs=[port('spec', 'rotor_spec')], outputs=[port('spec', 'rotor_spec')],
        defaults=copy.deepcopy(DEFAULTS['hawt']['corrections'])),
    'corrections_vertical': dict(
        family='specific', category='Corrections', label='VAWT corrections',
        description='Finite aspect ratio, flow curvature, dynamic stall, high induction, struts, shaft wake.',
        inputs=[port('spec', 'rotor_spec')], outputs=[port('spec', 'rotor_spec')],
        defaults=copy.deepcopy(DEFAULTS['vawt']['corrections'])),
    'solver': dict(
        family='specific', category='Solvers', label='Rotor solver',
        description='BEMT for axial rotors; single, double, multiple or double-multiple streamtube for VAWT.',
        inputs=[port('spec', 'rotor_spec')], outputs=[port('result', 'rotor_result'), port('values', 'record')],
        defaults={'method': 'auto', 'azimuth_tubes': 36}),
    'performance_curve': dict(
        family='specific', category='Solvers', label='Performance curve',
        description='Cp–λ for turbines, K_T/K_Q/η–J for propellers; reports the optimum.',
        inputs=[port('spec', 'rotor_spec')], outputs=[port('table', 'table'), port('values', 'record')],
        defaults={'variable': 'auto', 'start': None, 'stop': None, 'points': 21}),
    'design_checks': dict(
        family='specific', category='Constraints', label='Design checks',
        description='Domain limits: Betz, rating, tip speed/Mach, thrust, Keller, Burrill, cavitation, ripple.',
        inputs=[port('values', 'record')], outputs=[port('values', 'record'), port('report', 'report')],
        defaults={'checks': [{'preset': 'tip_speed'}], 'on_violation': 'report'}),
}


def catalog():
    from .constraints import OPERATORS, preset_catalog
    return {
        'types': list(TYPES),
        'blocks': [{'type': key, **copy.deepcopy(spec)} for key, spec in BLOCKS.items()],
        'constraint_presets': preset_catalog(), 'operators': list(OPERATORS),
        'spec_paths': ['geometry.*', 'operating.*', 'fluid.*', 'corrections.*', 'marine.*', 'method', 'section.name'],
    }
