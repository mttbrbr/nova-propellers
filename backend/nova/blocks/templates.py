"""Ready-made block workflows covering the main engineering cases."""
import copy


def _edge(source, source_port, target, target_port):
    return {'source': source, 'source_port': source_port, 'target': target, 'target_port': target_port}


def _node(id, type, config=None, x=0, y=0):
    return {'id': id, 'type': type, 'config': config or {}, 'position': {'x': x, 'y': y}}


_AOC_FRACTION = [i / 10 for i in range(11)]
_AOC_BLADE = [(8244850, 7643160, 49.75), (5729700, 10364760, 33.57), (2690000, 10999800, 21.68), (1923350, 12632760, 22.89),
              (1398800, 11158560, 18.99), (887700, 5896800, 16.80), (498995, 3832920, 15.59), (250170, 2336040, 12.37),
              (82314, 1174824, 11.24), (55818, 907200, 10.11), (29456, 641844, 8.98)]
_AOC_TOWER = [(151.1, 2.35e9), (141.7, 2.12e9), (135.6, 1.88e9), (132.2, 1.65e9), (130.7, 1.42e9), (130.3, 1.19e9),
              (130.3, 9.57e8), (129.8, 7.26e8), (128.2, 4.94e8), (124.6, 2.62e8), (118.4, 3.0e7)]

TEMPLATES = {
    'hawt_rated_design': {
        'name': 'HAWT rated design with limits',
        'description': 'Size a small wind turbine from requirements, check rating, tip speed and Betz, and draw Cp–λ.',
        'nodes': [
            _node('requirements', 'parameter_set', {'values': [
                {'name': 'radius', 'value': 5.0, 'unit': 'm', 'min': 1.0, 'max': 30.0},
                {'name': 'wind', 'value': 8.0, 'unit': 'm/s', 'min': 3.0, 'max': 25.0},
                {'name': 'tsr', 'value': 7.0, 'unit': '-', 'min': 3.0, 'max': 11.0}]}, 0, 0),
            _node('rotor', 'rotor_hawt', {'bindings': {'geometry.radius_m': 'radius', 'geometry.hub_radius_m': '0.1 * radius',
                                                     'geometry.design_tsr': 'tsr'}}, 280, 0),
            _node('operating', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 7.0},
                                                   'bindings': {'operating.velocity_m_s': 'wind', 'operating.tip_speed_ratio': 'tsr'}}, 560, 0),
            _node('corrections', 'corrections_axial', {'tip_loss': 'prandtl', 'hub_loss': 'prandtl', 'high_induction': 'buhl'}, 840, 0),
            _node('solver', 'solver', {'method': 'auto'}, 1120, -80),
            _node('curve', 'performance_curve', {'variable': 'auto', 'points': 21}, 1120, 120),
            _node('derived', 'expression', {'assignments': [{'name': 'power_kw', 'expression': 'power_w / 1000', 'unit': 'kW'}]}, 1400, -80),
            _node('checks', 'design_checks', {'checks': [{'preset': 'betz_limit'}, {'preset': 'rated_power', 'value': 10000},
                                                          {'preset': 'tip_speed', 'value': 80}], 'on_violation': 'report'}, 1680, -80),
            _node('report', 'report', {'title': 'HAWT design point'}, 1960, 0),
        ],
        'edges': [
            _edge('requirements', 'values', 'rotor', 'parameters'), _edge('rotor', 'spec', 'operating', 'spec'),
            _edge('requirements', 'values', 'operating', 'parameters'), _edge('operating', 'spec', 'corrections', 'spec'),
            _edge('corrections', 'spec', 'solver', 'spec'), _edge('corrections', 'spec', 'curve', 'spec'),
            _edge('solver', 'values', 'derived', 'values'), _edge('derived', 'values', 'checks', 'values'),
            _edge('checks', 'values', 'report', 'a'), _edge('curve', 'table', 'report', 'b'),
            _edge('checks', 'report', 'report', 'c'),
        ],
    },
    'vawt_dmst_study': {
        'name': 'VAWT DMST with corrections',
        'description': 'H-rotor analysed with double-multiple streamtube, dynamic stall and flow curvature; ripple and power limits.',
        'nodes': [
            _node('rotor', 'rotor_vawt', {}, 0, 0),
            _node('operating', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 3.0}}, 280, 0),
            _node('corrections', 'corrections_vertical', {'finite_aspect_ratio': True, 'flow_curvature': True,
                                                          'dynamic_stall': 'gormont_berg', 'high_induction': 'glauert',
                                                          'strut_drag': True, 'shaft_wake': True}, 560, 0),
            _node('solver', 'solver', {'method': 'double_multiple_streamtube', 'azimuth_tubes': 36}, 840, -80),
            _node('curve', 'performance_curve', {'variable': 'tip_speed_ratio', 'start': 1.0, 'stop': 6.0, 'points': 11}, 840, 120),
            _node('checks', 'design_checks', {'checks': [{'preset': 'betz_limit'}, {'preset': 'torque_ripple', 'value': 2.0},
                                                          {'preset': 'minimum_power', 'value': 100}], 'on_violation': 'report'}, 1120, -80),
            _node('report', 'report', {'title': 'VAWT operating point'}, 1400, 0),
        ],
        'edges': [
            _edge('rotor', 'spec', 'operating', 'spec'), _edge('operating', 'spec', 'corrections', 'spec'),
            _edge('corrections', 'spec', 'solver', 'spec'), _edge('corrections', 'spec', 'curve', 'spec'),
            _edge('solver', 'values', 'checks', 'values'), _edge('checks', 'values', 'report', 'a'),
            _edge('curve', 'table', 'report', 'b'), _edge('checks', 'report', 'report', 'c'),
        ],
    },
    'marine_cavitation': {
        'name': 'Marine propeller cavitation check',
        'description': 'B-series propeller behind a hull: open-water point, Keller, Burrill τc and local σ, stopping on violation.',
        'nodes': [
            _node('rotor', 'rotor_marine', {}, 0, 0),
            _node('operating', 'operating_point', {'fluid': {'preset': 'sea_water'}, 'operating': {'rpm': 120.0, 'advance_ratio': 0.6}}, 280, 0),
            _node('hull', 'marine_conditions', {'shaft_depth_m': 5.0, 'wake_fraction': 0.2, 'thrust_deduction': 0.15}, 560, 0),
            _node('solver', 'solver', {}, 840, -80),
            _node('curve', 'performance_curve', {'variable': 'advance_ratio', 'start': 0.1, 'stop': 1.1, 'points': 11}, 840, 120),
            _node('cavitation', 'design_checks', {'checks': [{'preset': 'keller'}, {'preset': 'burrill', 'value': 0.3},
                                                              {'preset': 'local_cavitation', 'value': 0.4, 'severity': 'soft'}],
                                                  'on_violation': 'stop'}, 1120, -80),
            _node('efficiency', 'design_checks', {'checks': [{'preset': 'min_open_water_efficiency', 'value': 0.55}]}, 1400, -80),
            _node('report', 'report', {'title': 'Propeller acceptance'}, 1680, 0),
        ],
        'edges': [
            _edge('rotor', 'spec', 'operating', 'spec'), _edge('operating', 'spec', 'hull', 'spec'),
            _edge('hull', 'spec', 'solver', 'spec'), _edge('hull', 'spec', 'curve', 'spec'),
            _edge('solver', 'values', 'cavitation', 'values'), _edge('cavitation', 'values', 'efficiency', 'values'),
            _edge('efficiency', 'values', 'report', 'a'), _edge('curve', 'table', 'report', 'b'),
            _edge('cavitation', 'report', 'report', 'c'), _edge('efficiency', 'report', 'report', 'd'),
        ],
    },
    'hawt_constrained_optimization': {
        'name': 'HAWT constrained optimisation',
        'description': 'Maximise Cp over design tip-speed ratio and pitch with a thrust limit (COBYLA).',
        'nodes': [
            _node('rotor', 'rotor_hawt', {}, 0, 0),
            _node('operating', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 7.0}}, 280, 0),
            _node('optimizer', 'optimizer', {'variables': [{'path': 'geometry.design_tsr', 'min': 4.0, 'max': 10.0},
                                                           {'path': 'operating.tip_speed_ratio', 'min': 4.0, 'max': 10.0},
                                                           {'path': 'geometry.pitch_deg', 'min': -3.0, 'max': 5.0}],
                                             'objective': 'CP', 'sense': 'maximize', 'method': 'cobyla', 'max_evaluations': 60,
                                             'checks': [{'quantity': 'thrust_n', 'operator': '<=', 'value': 2500, 'label': 'Tower thrust', 'unit': 'N'}]}, 560, 0),
            _node('checks', 'constraint', {'checks': [{'quantity': 'thrust_n', 'operator': '<=', 'value': 2500, 'label': 'Tower thrust', 'unit': 'N'},
                                                       {'quantity': 'CP', 'operator': '>=', 'value': 0.38, 'severity': 'soft', 'label': 'Target Cp'}]}, 840, 0),
            _node('report', 'report', {'title': 'Optimum rotor'}, 1120, 0),
        ],
        'edges': [
            _edge('rotor', 'spec', 'operating', 'spec'), _edge('operating', 'spec', 'optimizer', 'spec'),
            _edge('optimizer', 'values', 'checks', 'values'), _edge('checks', 'values', 'report', 'a'),
            _edge('optimizer', 'history', 'report', 'b'), _edge('checks', 'report', 'report', 'c'),
        ],
    },
    'propeller_sweep': {
        'name': 'Propeller diameter sweep',
        'description': 'Sweep diameter at fixed rpm, keep designs meeting thrust and tip Mach, select the most efficient.',
        'nodes': [
            _node('rotor', 'rotor_propeller', {}, 0, 0),
            _node('operating', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'rpm': 6000.0, 'velocity_m_s': 10.0}}, 280, 0),
            _node('sweep', 'sweep', {'path': 'geometry.diameter_m', 'start': 0.2, 'stop': 0.35, 'count': 7,
                                     'checks': [{'preset': 'min_thrust', 'value': 5.0}, {'preset': 'tip_mach', 'value': 0.6}]}, 560, 0),
            _node('feasible', 'filter', {'checks': [{'preset': 'min_thrust', 'value': 5.0}, {'preset': 'tip_mach', 'value': 0.6}]}, 840, 0),
            _node('best', 'select', {'objective': 'efficiency', 'sense': 'maximize'}, 1120, 0),
            _node('report', 'report', {'title': 'Selected propeller'}, 1400, 0),
        ],
        'edges': [
            _edge('rotor', 'spec', 'operating', 'spec'), _edge('operating', 'spec', 'sweep', 'spec'),
            _edge('sweep', 'table', 'feasible', 'table'), _edge('feasible', 'table', 'best', 'table'),
            _edge('best', 'values', 'report', 'a'), _edge('feasible', 'table', 'report', 'b'),
        ],
    },
    'openfast_limits': {
        'name': 'OpenFAST run with limits',
        'description': 'Run a self-contained OpenFAST case, reduce channels to statistics and check them against limits.',
        'nodes': [
            _node('case', 'openfast_case', {'case_directory': '', 'input_file': 'AOC_WSt/AOC_WSt.fst', 'output_file': 'AOC_WSt/AOC_WSt.outb', 'timeout_seconds': 600.0}, 0, 0),
            _node('run', 'openfast_run', {'integration_id': '', 'start_time_s': 1.0, 'statistics': [
                {'channel': 'GenPwr', 'stat': 'mean', 'name': 'gen_power_kw', 'unit': 'kW'},
                {'channel': 'RotSpeed', 'stat': 'max', 'name': 'rotor_speed_rpm_max', 'unit': 'rpm'},
                {'channel': 'RootMFlp3', 'stat': 'max', 'name': 'root_flap_moment_knm_max', 'unit': 'kN·m'}]}, 280, 0),
            _node('limits', 'constraint', {'checks': [
                {'quantity': 'rotor_speed_rpm_max', 'operator': '<=', 'value': 80, 'severity': 'hard', 'label': 'Rotor speed', 'unit': 'rpm'},
                {'quantity': 'gen_power_kw', 'operator': '>=', 'value': 0, 'severity': 'soft', 'label': 'Positive mean power', 'unit': 'kW'}],
                'on_violation': 'report'}, 560, 0),
            _node('report', 'report', {'title': 'OpenFAST run'}, 840, 0),
        ],
        'edges': [_edge('case', 'case', 'run', 'case'), _edge('run', 'values', 'limits', 'values'),
                  _edge('run', 'table', 'report', 'b'), _edge('limits', 'report', 'report', 'c')],
    },
    'openfast_rigid_vs_bemt': {
        'name': 'OpenFAST rigid rotor vs Nova BEMT',
        'description': 'Write a rigid-rotor OpenFAST case from a wind-turbine rotor, run it and compare power, thrust and torque with Nova\'s BEMT.',
        'nodes': [
            _node('rotor', 'rotor_hawt', {}, 0, 0),
            _node('operating', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 8.0, 'tip_speed_ratio': 7.0}}, 280, 0),
            _node('case', 'openfast_rotor_case', {'duration_s': 10.0, 'dt_s': 0.02, 'timeout_seconds': 600.0}, 560, 0),
            _node('run', 'openfast_run', {'integration_id': '', 'start_time_s': 5.0, 'statistics': [
                {'channel': 'RtAeroPwr', 'stat': 'mean', 'name': 'openfast_power_w', 'unit': 'W'},
                {'channel': 'RtAeroFxh', 'stat': 'mean', 'name': 'openfast_thrust_n', 'unit': 'N'},
                {'channel': 'RtAeroMxh', 'stat': 'mean', 'name': 'openfast_torque_nm', 'unit': 'N·m'}]}, 840, 0),
            _node('both', 'merge', {}, 1120, 0),
            _node('difference', 'expression', {'assignments': [
                {'name': 'power_difference_pct', 'expression': '100 * (openfast_power_w - nova_power_w) / nova_power_w', 'unit': '%'},
                {'name': 'thrust_difference_pct', 'expression': '100 * (openfast_thrust_n - nova_thrust_n) / nova_thrust_n', 'unit': '%'},
                {'name': 'torque_difference_pct', 'expression': '100 * (openfast_torque_nm - nova_torque_nm) / nova_torque_nm', 'unit': '%'}]}, 1400, 0),
            _node('report', 'report', {'title': 'OpenFAST vs Nova BEMT'}, 1680, 0),
        ],
        'edges': [_edge('rotor', 'spec', 'operating', 'spec'), _edge('operating', 'spec', 'case', 'spec'),
                  _edge('case', 'case', 'run', 'case'), _edge('case', 'reference', 'both', 'a'), _edge('run', 'values', 'both', 'b'),
                  _edge('both', 'values', 'difference', 'values'), _edge('run', 'table', 'report', 'b'),
                  _edge('difference', 'values', 'report', 'a')],
    },
    'openfast_flexible_example': {
        'name': 'OpenFAST flexible rotor (AOC 15/50 example structure)',
        'description': 'Flexible ElastoDyn model: hub, nacelle, tower and blade structure feed the case block. The structural numbers are the NREL '
                       'AOC 15/50 test data (r-test, Apache-2.0) on a 7.49 m rotor: an example to replace with your own data, not a validated design.',
        'nodes': [
            _node('rotor', 'rotor_hawt', {'geometry': {'blades': 3, 'radius_m': 7.49, 'hub_radius_m': 0.28, 'design_tsr': 5.0, 'stations': 24}}, 0, 0),
            _node('operating', 'operating_point', {'fluid': {'preset': 'air'}, 'operating': {'velocity_m_s': 10.0, 'rpm': 60.0}}, 280, 0),
            _node('hub', 'hub', {'mass_kg': 247.3, 'inertia_kg_m2': 9.0, 'cm_downwind_m': 0.0, 'precone_deg': 6.0}, 280, 220),
            _node('nacelle', 'nacelle', {'mass_kg': 1747.0, 'yaw_inertia_kg_m2': 976.3, 'overhang_m': 1.341, 'shaft_tilt_deg': 0.0,
                                         'tower_top_to_shaft_m': 0.6, 'cm_downwind_m': 0.0, 'cm_lateral_m': 0.0, 'cm_up_m': 0.6}, 280, 440),
            _node('tower', 'tower', {'shape': 'table', 'height_m': 24.4, 'base_height_m': 0.0, 'damping_pct': 3.0, 'stations': [
                {'height_fraction': x, 'mass_per_length_kg_m': m, 'fore_aft_stiffness_nm2': k, 'side_side_stiffness_nm2': k}
                for x, (m, k) in zip(_AOC_FRACTION, _AOC_TOWER)]}, 280, 660),
            _node('blade', 'blade_structure', {'tip_mass_kg': 5.9, 'flap_damping_pct': 4.0, 'edge_damping_pct': 4.0, 'stations': [
                {'span_fraction': x, 'mass_per_length_kg_m': m, 'flap_stiffness_nm2': fl, 'edge_stiffness_nm2': ed}
                for x, (fl, ed, m) in zip(_AOC_FRACTION, _AOC_BLADE)]}, 280, 880),
            _node('case', 'openfast_rotor_case', {'duration_s': 30.0, 'dt_s': 0.01, 'timeout_seconds': 900.0}, 560, 0),
            _node('run', 'openfast_run', {'integration_id': '', 'start_time_s': 20.0, 'statistics': [
                {'channel': 'RtAeroPwr', 'stat': 'mean', 'name': 'power_w', 'unit': 'W'},
                {'channel': 'RtAeroFxh', 'stat': 'mean', 'name': 'thrust_n', 'unit': 'N'},
                {'channel': 'TipDxb1', 'stat': 'max', 'name': 'tip_flap_m_max', 'unit': 'm'},
                {'channel': 'RootMFlp1', 'stat': 'max', 'name': 'root_flap_knm_max', 'unit': 'kN·m'},
                {'channel': 'TwrBsMyt', 'stat': 'max', 'name': 'tower_base_knm_max', 'unit': 'kN·m'}]}, 840, 0),
            _node('limits', 'constraint', {'checks': [
                {'quantity': 'tip_flap_m_max', 'operator': '<=', 'value': 0.75, 'severity': 'soft', 'label': 'Tip flap deflection (10 % of radius)', 'unit': 'm'}],
                'on_violation': 'report'}, 1120, 0),
            _node('report', 'report', {'title': 'Flexible OpenFAST run'}, 1400, 0),
        ],
        'edges': [_edge('rotor', 'spec', 'operating', 'spec'), _edge('operating', 'spec', 'case', 'spec'),
                  _edge('hub', 'hub', 'case', 'hub'), _edge('nacelle', 'nacelle', 'case', 'nacelle'),
                  _edge('tower', 'tower', 'case', 'tower'), _edge('blade', 'blade', 'case', 'blade'),
                  _edge('case', 'case', 'run', 'case'), _edge('run', 'values', 'limits', 'values'),
                  _edge('run', 'table', 'report', 'b'), _edge('limits', 'report', 'report', 'c')],
    },
}

_FLEX = {n['id']: n for n in TEMPLATES['openfast_flexible_example']['nodes']}
TEMPLATES['structural_campbell'] = {
    'name': 'Structural modes and Campbell diagram (AOC 15/50 example structure)',
    'description': 'Clamped and rotating blade modes, tower modes and the Campbell diagram with 1P/3P/6P margins, no aerodynamics. '
                   'Same example structure as the flexible OpenFAST template: replace it with your own data.',
    'nodes': [
        *(copy.deepcopy(_FLEX[k]) for k in ('rotor', 'operating', 'hub', 'nacelle', 'tower', 'blade')),
        _node('blade_clamped', 'blade_modes', {'flap_modes': 3, 'edge_modes': 2}, 560, 0),
        _node('blade_rotating', 'rotating_blade_modes', {'flap_modes': 3, 'edge_modes': 2}, 560, 220),
        _node('tower_modes', 'tower_modes', {'modes': 2}, 560, 440),
        _node('campbell', 'campbell', {'rpm_max': 80.0, 'points': 41}, 560, 660),
        _node('margins', 'constraint', {'checks': [
            {'quantity': 'min_excitation_margin_pct', 'operator': '>=', 'value': 10.0, 'severity': 'soft',
             'label': 'Distance of every mode from 1P/3P/6P at the operating speed', 'unit': '%'}],
            'on_violation': 'report'}, 840, 660),
        _node('report', 'report', {'title': 'Structural modes'}, 1120, 660),
    ],
    'edges': [_edge('rotor', 'spec', 'operating', 'spec'),
              _edge('blade', 'blade', 'blade_clamped', 'blade'), _edge('operating', 'spec', 'blade_clamped', 'spec'),
              _edge('blade', 'blade', 'blade_rotating', 'blade'), _edge('operating', 'spec', 'blade_rotating', 'spec'),
              _edge('tower', 'tower', 'tower_modes', 'tower'), _edge('nacelle', 'nacelle', 'tower_modes', 'nacelle'),
              _edge('hub', 'hub', 'tower_modes', 'hub'), _edge('blade', 'blade', 'tower_modes', 'blade'),
              _edge('operating', 'spec', 'tower_modes', 'spec'),
              _edge('blade', 'blade', 'campbell', 'blade'), _edge('operating', 'spec', 'campbell', 'spec'),
              _edge('tower', 'tower', 'campbell', 'tower'), _edge('nacelle', 'nacelle', 'campbell', 'nacelle'),
              _edge('hub', 'hub', 'campbell', 'hub'),
              _edge('campbell', 'values', 'margins', 'values'), _edge('campbell', 'table', 'report', 'b'),
              _edge('margins', 'report', 'report', 'c')],
}


def templates():
    return [{'id': key, 'name': t['name'], 'description': t['description']} for key, t in TEMPLATES.items()]


def layout(nodes, edges, columns=4):
    """Layered left-to-right layout that wraps long chains into bands."""
    depth = {n['id']: 0 for n in nodes}
    for _ in nodes:
        for e in edges:
            depth[e['target']] = max(depth[e['target']], depth[e['source']] + 1)
    counts = {}
    for node in nodes:
        level = depth[node['id']]
        slot = (level // columns, level % columns)
        counts[slot] = counts.get(slot, 0) + 1
    offsets, top = {}, 0  # a band starts below the tallest column of the band above it
    for band in sorted({b for b, _ in counts}):
        offsets[band] = top
        top += max(n for (b, _), n in counts.items() if b == band) * 150 + 60
    rows = {}
    for node in nodes:
        level = depth[node['id']]
        slot = (level // columns, level % columns)
        row = rows.get(slot, 0)
        rows[slot] = row + 1
        node['position'] = {'x': slot[1] * 270, 'y': offsets[slot[0]] + row * 150}
    return nodes


def template(key):
    if key not in TEMPLATES:
        raise ValueError(f'Unknown block template {key!r}')
    from nova.blocks.catalog import BLOCKS
    t = copy.deepcopy(TEMPLATES[key])
    for node in t['nodes']:  # every setting is visible and editable, including those the template leaves at their default
        node['config'] = {**copy.deepcopy(BLOCKS[node['type']]['defaults']), **node['config']}
    layout(t['nodes'], t['edges'])
    return {'schema_version': 2, 'kind': 'blocks', 'template': key, **t}
