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

TYPES = ('record', 'rotor_spec', 'rotor_result', 'table', 'report', 'openfast_case', 'hub', 'nacelle', 'tower', 'blade',
         'attachment', 'modal')


def port(name, kind, optional=False, label=None):
    return {'name': name, 'type': kind, 'optional': optional, 'label': label or name}


def _rotor_defaults(kind):
    d = copy.deepcopy(DEFAULTS[kind])
    config = {'geometry': d['geometry'], 'section': d['section'], 'method': d['method'], 'bindings': {}}
    if kind in ('hawt', 'propeller'):
        config['sections'] = []  # different sections along the span; empty = the single section above
    return config


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
        description='Tip loss, hub loss, high induction, rotational augmentation, compressibility — only those applicable to the connected rotor are applied.',
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
    # ----------------------------------------------------------- OpenFAST
    'openfast_case': dict(
        family='specific', category='OpenFAST', label='OpenFAST case',
        description='Self-contained OpenFAST input folder (absolute path), its .fst file and the expected output. Inspected, never edited.',
        inputs=[], outputs=[port('case', 'openfast_case')],
        defaults={'case_directory': '', 'input_file': 'model.fst', 'output_file': 'model.outb', 'timeout_seconds': 600.0}),
    'hub': dict(
        family='specific', category='OpenFAST structure', label='Hub',
        description='Hub mass, inertia about the rotor axis, centre of mass and blade precone. Required values start empty: nothing is assumed.',
        inputs=[], outputs=[port('hub', 'hub')],
        defaults={'mass_kg': None, 'inertia_kg_m2': None, 'cm_downwind_m': 0.0, 'precone_deg': 0.0}),
    'nacelle': dict(
        family='specific', category='OpenFAST structure', label='Nacelle & shaft',
        description='Nacelle mass and yaw inertia, centre of mass from the tower top, rotor overhang, shaft tilt and tower-top-to-shaft height.',
        inputs=[], outputs=[port('nacelle', 'nacelle')],
        defaults={'mass_kg': None, 'yaw_inertia_kg_m2': None, 'overhang_m': None, 'shaft_tilt_deg': 0.0, 'tower_top_to_shaft_m': None,
                  'cm_downwind_m': 0.0, 'cm_lateral_m': 0.0, 'cm_up_m': 0.0}),
    'tower': dict(
        family='specific', category='OpenFAST structure', label='Tower',
        description='Tubular steel tower from diameters and wall (mass and stiffness follow from the material), or a table of mass and bending stiffness over the height.',
        inputs=[], outputs=[port('tower', 'tower')],
        defaults={'shape': 'tubular', 'height_m': None, 'base_height_m': 0.0, 'base_diameter_m': None, 'top_diameter_m': None,
                  'wall_thickness_m': None, 'youngs_modulus_pa': 2.1e11, 'density_kg_m3': 7850.0, 'damping_pct': 1.0, 'stations': []}),
    'blade_structure': dict(
        family='specific', category='OpenFAST structure', label='Blade structure',
        description='Mass per length and flap/edge bending stiffness along the span (0 = root, 1 = tip), tip mass and damping. Optional columns for the '
                    '3-D beam: structural_twist_deg, axial_stiffness_n, torsional_stiffness_nm2, edge/flap_shear_stiffness_n, torsional/flap/edge_inertia_kg_m '
                    '(about the centre of mass), cm_offset_m (chordwise).',
        inputs=[], outputs=[port('blade', 'blade')],
        defaults={'stations': [], 'tip_mass_kg': 0.0, 'flap_damping_pct': 1.0, 'edge_damping_pct': 1.0}),
    'openfast_rotor_case': dict(
        family='specific', category='OpenFAST', label='OpenFAST case from rotor',
        description='Writes an OpenFAST case from the connected horizontal-axis rotor and its operating point. With only the rotor it is rigid '
                    '(Simplified ElastoDyn); connect hub, nacelle, tower and blade structure for a flexible ElastoDyn model at prescribed rotor speed. '
                    'Airfoil tables are Nova\'s own polars. Also emits Nova\'s BEMT result (and the computed modal frequencies) as a reference.',
        inputs=[port('spec', 'rotor_spec'), port('hub', 'hub', True), port('nacelle', 'nacelle', True), port('tower', 'tower', True),
                port('blade', 'blade', True)],
        outputs=[port('case', 'openfast_case'), port('reference', 'record')],
        defaults={'duration_s': 10.0, 'dt_s': 0.02, 'hub_height_m': None, 'overhang_m': None, 'shaft_tilt_deg': 0.0,
                  'precone_deg': 0.0, 'flap_dof': True, 'edge_dof': True, 'tower_fa_dof': True, 'tower_ss_dof': True,
                  'timeout_seconds': 600.0}),
    'openfast_run': dict(
        family='specific', category='OpenFAST', label='OpenFAST run',
        description='Runs the case with the OpenFAST executable configured in Settings → Integrations, then reduces every channel to '
                    'statistics over the window from start_time_s. The named statistics feed constraints and reports.',
        inputs=[port('case', 'openfast_case')], outputs=[port('table', 'table'), port('values', 'record')],
        defaults={'integration_id': '', 'start_time_s': 0.0,
                  'statistics': [{'channel': 'GenPwr', 'stat': 'mean', 'name': 'gen_power_kw', 'unit': 'kW'}]}),
    # ------------------------------------------------------------ structural dynamics (no aerodynamics)
    'point_mass': dict(
        family='specific', category='Structural dynamics', label='Point mass',
        description='Concentrated mass and/or rotary inertia at a position along the blade or tower (0 = clamped end, 1 = free end). '
                    'Chain several attachment blocks: each appends its item to the list received upstream.',
        inputs=[port('attachments', 'attachment', True)], outputs=[port('attachments', 'attachment')],
        defaults={'target': 'blade', 'position': 1.0, 'mass_kg': 0.0, 'inertia_kg_m2': 0.0, 'direction': 'both'}),
    'spring_damper': dict(
        family='specific', category='Structural dynamics', label='Spring & damper',
        description='Grounded translational and/or rotational spring and viscous damper at a position along the blade or tower '
                    '(e.g. guy wires, tuned dampers, foundation). Any non-zero damper switches the solution to damped modes.',
        inputs=[port('attachments', 'attachment', True)], outputs=[port('attachments', 'attachment')],
        defaults={'target': 'tower', 'position': 1.0, 'stiffness_n_m': 0.0, 'damping_ns_m': 0.0, 'rotational_stiffness_nm_rad': 0.0,
                  'rotational_damping_nms_rad': 0.0, 'direction': 'both'}),
    'blade_modes': dict(
        family='specific', category='Structural dynamics', label='Blade modes (clamped)',
        description='Natural frequencies and coupled mode shapes (flap, edge, torsion) of the non-rotating blade clamped at the root, 3-D beam. '
                    'Length from the connected rotor (tip − hub radius) or length_m.',
        inputs=[port('blade', 'blade'), port('spec', 'rotor_spec', True), port('attachments', 'attachment', True)],
        outputs=[port('table', 'table'), port('values', 'record'), port('modal', 'modal')],
        defaults={'length_m': None, 'flap_modes': 3, 'edge_modes': 2, 'torsion_modes': 1, 'use_aerodynamic_twist': True}),
    'rotating_blade_modes': dict(
        family='specific', category='Structural dynamics', label='Blade modes (rotating)',
        description='Blade modes at a rotor speed: centrifugal stiffening, spin softening, Coriolis and propeller-moment terms (3-D beam). '
                    'rpm empty = operating speed of the connected rotor.',
        inputs=[port('blade', 'blade'), port('spec', 'rotor_spec', True), port('attachments', 'attachment', True)],
        outputs=[port('table', 'table'), port('values', 'record'), port('modal', 'modal')],
        defaults={'length_m': None, 'rpm': None, 'flap_modes': 3, 'edge_modes': 2, 'torsion_modes': 1, 'use_aerodynamic_twist': True}),
    'tower_modes': dict(
        family='specific', category='Structural dynamics', label='Tower modes',
        description='Fore-aft, side-to-side and torsion modes of the tower clamped at the base (3-D beam), with the nacelle (offset centre of mass, '
                    'yaw inertia) and the parked rotor as rigid bodies at the top, or top_mass_kg and top_inertia_kg_m2.',
        inputs=[port('tower', 'tower'), port('nacelle', 'nacelle', True), port('hub', 'hub', True), port('blade', 'blade', True),
                port('spec', 'rotor_spec', True), port('attachments', 'attachment', True)],
        outputs=[port('table', 'table'), port('values', 'record'), port('modal', 'modal')],
        defaults={'modes': 2, 'torsion_modes': 1, 'top_mass_kg': None, 'top_inertia_kg_m2': 0.0}),
    'campbell': dict(
        family='specific', category='Structural dynamics', label='Campbell diagram',
        description='Blade (rotating frame) and tower frequencies against rotor speed with the 1P, BP, 2BP excitation lines (or your '
                    'harmonics), crossings and the smallest margin at the operating speed. Modes are tracked between speeds by MAC.',
        inputs=[port('blade', 'blade'), port('spec', 'rotor_spec'), port('tower', 'tower', True), port('nacelle', 'nacelle', True),
                port('hub', 'hub', True), port('attachments', 'attachment', True)],
        outputs=[port('table', 'table'), port('values', 'record'), port('modal', 'modal')],
        defaults={'rpm_min': 0.0, 'rpm_max': None, 'points': 31, 'operating_rpm': None, 'flap_modes': 2, 'edge_modes': 1,
                  'torsion_modes': 0, 'tower_modes': 2, 'tower_torsion_modes': 0, 'harmonics': [], 'use_aerodynamic_twist': True,
                  'top_mass_kg': None, 'top_inertia_kg_m2': 0.0}),
}


def catalog():
    from .constraints import OPERATORS, preset_catalog
    return {
        'types': list(TYPES),
        'blocks': [{'type': key, **copy.deepcopy(spec)} for key, spec in BLOCKS.items()],
        'constraint_presets': preset_catalog(), 'operators': list(OPERATORS),
        'spec_paths': ['geometry.*', 'operating.*', 'fluid.*', 'corrections.*', 'marine.*', 'method', 'section.name'],
    }
