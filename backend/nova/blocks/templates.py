"""Ready-made block workflows covering the main engineering cases."""
import copy


def _edge(source, source_port, target, target_port):
    return {'source': source, 'source_port': source_port, 'target': target, 'target_port': target_port}


def _node(id, type, config=None, x=0, y=0):
    return {'id': id, 'type': type, 'config': config or {}, 'position': {'x': x, 'y': y}}


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
}


def templates():
    return [{'id': key, 'name': t['name'], 'description': t['description']} for key, t in TEMPLATES.items()]


def template(key):
    if key not in TEMPLATES:
        raise ValueError(f'Unknown block template {key!r}')
    t = copy.deepcopy(TEMPLATES[key])
    return {'schema_version': 2, 'kind': 'blocks', 'template': key, **t}
