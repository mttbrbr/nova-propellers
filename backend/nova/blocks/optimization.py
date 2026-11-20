"""Design optimisation over the whole downstream workflow (phase 3).

The optimiser blocks vary specification fields of the connected rotor and, for every candidate, re-run the
blocks downstream of themselves (solvers, structural and cost blocks, constraints…). Objectives and
constraints may therefore use any quantity that any downstream block emits — mass, power, thrust,
frequencies, cost, LCOE — not only the rotor solver outputs. Constraint blocks downstream count as hard
constraints when their checks are hard.

* design_optimizer – one objective (or a weighted sum), gradient-based SQP (SciPy SLSQP with finite
                     differences) or derivative-free COBYLA.
* pareto_optimizer – several objectives, NSGA-II (non-dominated sorting, crowding distance, simulated
                     binary crossover and polynomial mutation, constrained domination). Emits the Pareto
                     front and the knee point.
* multi_fidelity   – a sequence of fidelity levels: cheap models far from the optimum, the full model in a
                     shrinking trust region, the downstream chain (e.g. finite elements, costs) only at the end.
"""
import contextvars
import copy
import math

import numpy as np

from nova.physics import rotors

from .constraints import evaluate_check, normalise, penalty, report
from .expressions import ExpressionError, evaluate

DOWNSTREAM = contextvars.ContextVar('optimizer_downstream', default=None)
MAX_EVALUATIONS = 2000


class OptimizationError(ValueError):
    pass


class _Budget(Exception):
    pass


def _number(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise OptimizationError(f'{label} must be a finite number')
    return float(value)


def _integer(config, key, low, high, default):
    value = config.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise OptimizationError(f'{key} must be an integer in {low}–{high}')
    return value


def _variables(config):
    from .performance import apply
    variables = config.get('variables') or []
    if not 1 <= len(variables) <= 12:
        raise OptimizationError('Optimise 1–12 variables')
    bounds = []
    for item in variables:
        apply({}, item.get('path'), 0.0)
        lo, hi = _number(item.get('min'), f'{item.get("path")} minimum'), _number(item.get('max'), f'{item.get("path")} maximum')
        if hi <= lo:
            raise OptimizationError(f'{item["path"]}: maximum must exceed minimum')
        bounds.append((lo, hi))
    return variables, np.array(bounds)


def _objectives(config):
    items = config.get('objectives')
    if items is None:
        items = [{'expression': config.get('objective', 'CP'), 'sense': config.get('sense', 'maximize'), 'weight': 1.0}]
    if not isinstance(items, list) or not 1 <= len(items) <= 4:
        raise OptimizationError('Give 1–4 objectives')
    out = []
    for item in items:
        if item.get('sense', 'minimize') not in ('maximize', 'minimize') or not isinstance(item.get('expression'), str):
            raise OptimizationError('Every objective needs an expression and a sense (maximize or minimize)')
        out.append({'expression': item['expression'], 'sense': item.get('sense', 'minimize'),
                    'weight': _number(item.get('weight', 1.0), 'weight')})
    return out


class Evaluator:
    """Evaluates candidates: rotor analysis plus the downstream workflow, with a budget and a history."""

    def __init__(self, base_spec, variables, checks, budget, cancelled=None, downstream=True, overrides=None):
        from .performance import apply
        self.apply = apply
        self.base, self.variables, self.checks = base_spec, variables, checks
        self.budget, self.cancelled = budget, cancelled
        self.downstream = DOWNSTREAM.get() if downstream else None
        self.overrides = overrides or {}
        self.history, self.cache = [], {}
        self.label = None

    def spec(self, x):
        spec = copy.deepcopy(self.base)
        for path, value in self.overrides.items():
            self.apply(spec, path, value)
        for item, value in zip(self.variables, x):
            self.apply(spec, item['path'], float(value))
        return spec

    def __call__(self, x):
        key = (self.label, tuple(round(float(v), 10) for v in x))
        if key in self.cache:
            return self.cache[key]
        if len(self.history) >= self.budget:
            raise _Budget
        if self.cancelled and self.cancelled():
            raise InterruptedError('Run cancelled')
        entry = {'evaluation': len(self.history) + 1, **({'level': self.label} if self.label is not None else {}),
                 **{item['path']: float(v) for item, v in zip(self.variables, x)}}
        spec = self.spec(x)
        outcome = None
        try:
            record = {}
            try:
                result = rotors.analyze(spec)
                record.update(rotors.scalar_outputs(result))
                record['converged'] = 1.0 if result['converged'] else 0.0
            except (ValueError, KeyError) as exc:
                if self.downstream is None:
                    raise ValueError(str(exc)) from exc
            feasible, violation = True, 0.0
            if self.downstream is not None:
                values = dict(record)
                extra, feasible, violation = self.downstream({'spec': spec, 'values': values, 'history': {'kind': 'optimization', 'rows': []},
                                                              'table': {'kind': 'pareto', 'rows': []}})
                record.update(extra)
            own = report(self.checks, record)
            feasible = feasible and own['feasible']
            violation += penalty(self.checks, record)
            entry.update(state='succeeded', feasible=feasible, penalty=violation)
            outcome = {'record': record, 'feasible': feasible, 'penalty': violation, 'spec': spec}
        except (ValueError, ExpressionError) as exc:
            entry.update(state='failed', error=str(exc), feasible=False, penalty=1.0)
        self.history.append(entry)
        self.cache[key] = (outcome, entry)
        return outcome, entry


def _score(objectives, record):
    """Signed objective values (all to be minimised)."""
    return [(-1.0 if o['sense'] == 'maximize' else 1.0) * float(evaluate(o['expression'], record)) for o in objectives]


def _finish(evaluator, best, variables, objectives, extra_values=None):
    outcome = best[0]
    values = {k: v for k, v in outcome['record'].items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    for i, o in enumerate(objectives):
        try:
            values['objective' if i == 0 else f'objective_{i + 1}'] = float(evaluate(o['expression'], outcome['record']))
        except ExpressionError:
            pass
    values.update({'feasible': 1.0 if outcome['feasible'] else 0.0, 'evaluations': float(len(evaluator.history)), **(extra_values or {})})
    for item in variables:
        values[item['path'].split('.')[-1]] = best[1][item['path']]
    return values


def _rank(entry_outcome, objectives):
    outcome, entry = entry_outcome
    try:
        score = sum(o['weight'] * s for o, s in zip(objectives, _score(objectives, outcome['record'])))
    except ExpressionError:
        score = math.inf
    return (0 if outcome['feasible'] else 1, outcome['penalty'], score)


# ------------------------------------------------------------------ single objective

def _local(evaluator, objectives, checks, bounds, start, method, budget, scale_hint=None):
    """SLSQP or COBYLA on the unit box; returns nothing (results are in the evaluator's history)."""
    from scipy.optimize import minimize
    span = bounds[:, 1] - bounds[:, 0]
    scale = [scale_hint]

    def physical(u):
        return bounds[:, 0] + np.clip(u, 0, 1) * span

    def merit(u):
        outcome, _ = evaluator(physical(u))
        if outcome is None:
            return 1e6
        try:
            value = sum(o['weight'] * s for o, s in zip(objectives, _score(objectives, outcome['record'])))
        except ExpressionError:
            return 1e6
        if scale[0] is None:
            scale[0] = max(abs(value), 1e-9)
        return value / scale[0]

    def margin(check):
        def g(u):
            outcome, _ = evaluator(physical(u))
            if outcome is None:
                return -1.0
            item = evaluate_check(check, outcome['record'])
            return item['margin'] if item['margin'] is not None else -1.0
        return g

    def downstream_feasible(u):
        outcome, _ = evaluator(physical(u))
        if outcome is None:
            return -1.0
        return -outcome['penalty'] if not outcome['feasible'] else 0.0

    hard = [c for c in checks if normalise(c)['severity'] == 'hard']
    constraints = [{'type': 'ineq', 'fun': margin(c)} for c in hard]
    if evaluator.downstream is not None:
        constraints.append({'type': 'ineq', 'fun': downstream_feasible})
    try:
        if method == 'slsqp':
            minimize(merit, start, method='SLSQP', bounds=[(0, 1)] * len(start), constraints=constraints,
                     options={'maxiter': max(budget // (len(start) + 1), 2), 'ftol': 1e-7, 'eps': 1e-3})
        else:
            box = [{'type': 'ineq', 'fun': (lambda u, j=j: u[j])} for j in range(len(start))]
            box += [{'type': 'ineq', 'fun': (lambda u, j=j: 1 - u[j])} for j in range(len(start))]
            minimize(merit, start, method='COBYLA', constraints=box + constraints,
                     options={'maxiter': budget, 'rhobeg': 0.25, 'tol': 1e-5})
    except _Budget:
        pass


def _best(evaluator, objectives):
    done = [evaluator.cache[k] for k in evaluator.cache if evaluator.cache[k][0] is not None]
    if not done:
        raise OptimizationError('No evaluation succeeded')
    return min(done, key=lambda item: _rank(item, objectives))


def design_optimizer(node, args, cancelled=None):
    config = node.get('config', {})
    variables, bounds = _variables(config)
    objectives = _objectives(config)
    checks = config.get('checks') or []
    for c in checks:
        normalise(c)
    method = config.get('method', 'slsqp')
    if method not in ('slsqp', 'cobyla'):
        raise OptimizationError('method must be slsqp or cobyla')
    budget = _integer(config, 'max_evaluations', 4, MAX_EVALUATIONS, 120)
    evaluator = Evaluator(args['spec'], variables, checks, budget, cancelled, downstream=config.get('evaluate_downstream', True))
    start = np.array([np.clip((item.get('initial', (lo + hi) / 2) - lo) / (hi - lo), 0, 1) for item, (lo, hi) in zip(variables, bounds)])
    _local(evaluator, objectives, checks, bounds, start, method, budget)
    best = _best(evaluator, objectives)
    notes = [f'{"SQP (SLSQP, finite-difference gradients)" if method == "slsqp" else "COBYLA"} over {len(variables)} variables, '
             f'{len(evaluator.history)} evaluations' + (', each re-running the downstream blocks' if evaluator.downstream else '')]
    if not best[0]['feasible']:
        notes.append('No feasible design found: the least-violating one is reported')
    return {'spec': best[0]['spec'], 'values': _finish(evaluator, best, variables, objectives),
            'history': {'kind': 'optimization', 'variables': [v['path'] for v in variables], 'objective': objectives[0]['expression'],
                        'sense': objectives[0]['sense'], 'method': method, 'rows': evaluator.history,
                        'best_evaluation': best[1]['evaluation']}, 'notes': notes}


# ------------------------------------------------------------------ NSGA-II

def _dominates(a, b):
    """Constrained domination (Deb): feasible beats infeasible, smaller violation wins, then Pareto domination."""
    if a['feasible'] != b['feasible']:
        return a['feasible']
    if not a['feasible']:
        return a['penalty'] < b['penalty']
    return all(x <= y for x, y in zip(a['f'], b['f'])) and any(x < y for x, y in zip(a['f'], b['f']))


def _fronts(pop):
    n = len(pop)
    dominated = [[] for _ in range(n)]
    count = [0] * n
    fronts = [[]]
    for i in range(n):
        for j in range(n):
            if i != j:
                if _dominates(pop[i], pop[j]):
                    dominated[i].append(j)
                elif _dominates(pop[j], pop[i]):
                    count[i] += 1
        if count[i] == 0:
            fronts[0].append(i)
    k = 0
    while fronts[k]:
        nxt = []
        for i in fronts[k]:
            for j in dominated[i]:
                count[j] -= 1
                if count[j] == 0:
                    nxt.append(j)
        k += 1
        fronts.append(nxt)
    return fronts[:-1]


def _crowding(pop, front):
    distance = {i: 0.0 for i in front}
    if len(front) <= 2:
        return {i: math.inf for i in front}
    for m in range(len(pop[front[0]]['f'])):
        ordered = sorted(front, key=lambda i: pop[i]['f'][m])
        lo, hi = pop[ordered[0]]['f'][m], pop[ordered[-1]]['f'][m]
        distance[ordered[0]] = distance[ordered[-1]] = math.inf
        if hi - lo <= 0:
            continue
        for a, b, c in zip(ordered, ordered[1:], ordered[2:]):
            distance[b] += (pop[c]['f'][m] - pop[a]['f'][m]) / (hi - lo)
    return distance


def _sbx(rng, a, b, eta=15.0):
    child1, child2 = a.copy(), b.copy()
    for i in range(len(a)):
        if rng.random() > 0.5 or abs(a[i] - b[i]) < 1e-14:
            continue
        u = rng.random()
        beta = (2 * u) ** (1 / (eta + 1)) if u <= 0.5 else (1 / (2 * (1 - u))) ** (1 / (eta + 1))
        child1[i] = 0.5 * ((1 + beta) * a[i] + (1 - beta) * b[i])
        child2[i] = 0.5 * ((1 - beta) * a[i] + (1 + beta) * b[i])
    return np.clip(child1, 0, 1), np.clip(child2, 0, 1)


def _mutate(rng, x, eta=20.0):
    y = x.copy()
    for i in range(len(x)):
        if rng.random() > 1.0 / len(x):
            continue
        u = rng.random()
        delta = (2 * u) ** (1 / (eta + 1)) - 1 if u < 0.5 else 1 - (2 * (1 - u)) ** (1 / (eta + 1))
        y[i] = np.clip(y[i] + delta, 0, 1)
    return y


def pareto_optimizer(node, args, cancelled=None):
    config = node.get('config', {})
    variables, bounds = _variables(config)
    objectives = _objectives(config)
    if len(objectives) < 2:
        raise OptimizationError('A Pareto optimisation needs 2–4 objectives')
    checks = config.get('checks') or []
    for c in checks:
        normalise(c)
    size = _integer(config, 'population', 4, 200, 24)
    size += size % 2
    generations = _integer(config, 'generations', 1, 200, 15)
    rng = np.random.default_rng(_integer(config, 'seed', 0, 2**31 - 1, 1))
    budget = size * (generations + 1)
    if budget > MAX_EVALUATIONS:
        raise OptimizationError(f'population × (generations + 1) must stay within {MAX_EVALUATIONS} evaluations')
    evaluator = Evaluator(args['spec'], variables, checks, budget + 1, cancelled, downstream=config.get('evaluate_downstream', True))
    span = bounds[:, 1] - bounds[:, 0]

    def individual(u):
        outcome, entry = evaluator(bounds[:, 0] + u * span)
        if outcome is None:
            return {'u': u, 'f': [math.inf] * len(objectives), 'feasible': False, 'penalty': math.inf, 'entry': entry}
        try:
            f = _score(objectives, outcome['record'])
        except ExpressionError as exc:
            entry.update(state='failed', error=str(exc))
            return {'u': u, 'f': [math.inf] * len(objectives), 'feasible': False, 'penalty': math.inf, 'entry': entry}
        return {'u': u, 'f': f, 'feasible': outcome['feasible'], 'penalty': outcome['penalty'], 'entry': entry, 'outcome': outcome}

    # Latin-hypercube start
    dims = len(variables)
    lhs = (np.argsort(rng.random((dims, size)), axis=1).T + rng.random((size, dims))) / size
    population = [individual(u) for u in lhs]

    def select(pop):
        fronts = _fronts(pop)
        rank, crowd = {}, {}
        for k, front in enumerate(fronts):
            for i in front:
                rank[i] = k
            crowd.update(_crowding(pop, front))
        return rank, crowd, fronts

    for generation in range(generations):
        if cancelled and cancelled():
            raise InterruptedError('Run cancelled')
        rank, crowd, _ = select(population)

        def tournament():
            a, b = rng.integers(len(population), size=2)
            if rank[a] != rank[b]:
                return population[a if rank[a] < rank[b] else b]
            return population[a if crowd[a] >= crowd[b] else b]
        children = []
        while len(children) < size:
            c1, c2 = _sbx(rng, tournament()['u'], tournament()['u'])
            children += [individual(_mutate(rng, c1)), individual(_mutate(rng, c2))]
        merged = population + children[:size]
        rank, crowd, fronts = select(merged)
        survivors = []
        for front in fronts:
            if len(survivors) + len(front) <= size:
                survivors += front
            else:
                survivors += sorted(front, key=lambda i: -crowd[i])[:size - len(survivors)]
                break
        population = [merged[i] for i in survivors]
        for p in population:
            p['entry'].setdefault('generation', generation + 1)
    rank, _, fronts = select(population)
    front = [population[i] for i in fronts[0] if population[i]['feasible'] and 'outcome' in population[i]]
    if not front:
        raise OptimizationError('No feasible design on the final front')
    f = np.array([p['f'] for p in front])
    lo, hi = f.min(axis=0), f.max(axis=0)
    normalised = (f - lo) / np.where(hi > lo, hi - lo, 1.0)
    knee = front[int(np.argmin(np.linalg.norm(normalised, axis=1)))]
    rows = []
    for p in sorted(front, key=lambda p: p['f'][0]):
        row = {item['path']: float(bounds[d, 0] + p['u'][d] * span[d]) for d, item in enumerate(variables)}
        for o in objectives:
            row[o['expression']] = float(evaluate(o['expression'], p['outcome']['record']))
        row['knee'] = p is knee
        rows.append(row)
    values = _finish(evaluator, (knee['outcome'], knee['entry']), variables, objectives, {'pareto_points': float(len(front))})
    notes = [f'NSGA-II: population {size}, {generations} generations, {len(evaluator.history)} evaluations; constrained domination; '
             'the knee point (closest to the ideal point after normalising each objective) is emitted']
    return {'spec': knee['outcome']['spec'], 'values': values,
            'table': {'kind': 'pareto', 'objectives': [o['expression'] for o in objectives], 'senses': [o['sense'] for o in objectives],
                      'rows': rows, 'history': evaluator.history}, 'notes': notes}


# ------------------------------------------------------------------ multi-fidelity

DEFAULT_LEVELS = [
    {'label': 'coarse', 'overrides': {'geometry.stations': 8}, 'evaluations': 40, 'trust_region': 1.0, 'downstream': False},
    {'label': 'full BEMT', 'overrides': {}, 'evaluations': 30, 'trust_region': 0.3, 'downstream': False},
    {'label': 'full chain', 'overrides': {}, 'evaluations': 15, 'trust_region': 0.1, 'downstream': True},
]


def multi_fidelity(node, args, cancelled=None):
    config = node.get('config', {})
    variables, bounds = _variables(config)
    base_objectives = _objectives(config)
    checks = config.get('checks') or []
    for c in checks:
        normalise(c)
    levels = config.get('levels') or DEFAULT_LEVELS
    if not isinstance(levels, list) or not 1 <= len(levels) <= 6:
        raise OptimizationError('Give 1–6 fidelity levels')
    span = bounds[:, 1] - bounds[:, 0]
    centre = np.array([np.clip((item.get('initial', (lo + hi) / 2) - lo) / (hi - lo), 0, 1) for item, (lo, hi) in zip(variables, bounds)])
    history, summary, best = [], [], None
    for index, level in enumerate(levels):
        budget = level.get('evaluations', 20)
        if type(budget) is not int or not 2 <= budget <= 500:
            raise OptimizationError('Each level needs 2–500 evaluations')
        region = _number(level.get('trust_region', 1.0), 'trust_region')
        if not 0 < region <= 1:
            raise OptimizationError('trust_region must be in (0, 1]')
        objectives = _objectives(level) if level.get('objective') or level.get('objectives') else base_objectives
        overrides = level.get('overrides') or {}
        if not isinstance(overrides, dict):
            raise OptimizationError('overrides must map specification paths to values')
        lo = np.clip(centre - region / 2 if region < 1 else 0 * centre, 0, 1)
        hi = np.clip(centre + region / 2 if region < 1 else 0 * centre + 1, 0, 1)
        local_bounds = np.stack([bounds[:, 0] + lo * span, bounds[:, 0] + hi * span], axis=1)
        local_bounds[:, 1] = np.maximum(local_bounds[:, 1], local_bounds[:, 0] + 1e-9 * span)
        evaluator = Evaluator(args['spec'], variables, checks, budget, cancelled, downstream=bool(level.get('downstream', False)),
                              overrides=overrides)
        evaluator.label = level.get('label', f'level {index + 1}')
        start = np.clip((bounds[:, 0] + centre * span - local_bounds[:, 0]) / (local_bounds[:, 1] - local_bounds[:, 0]), 0, 1)
        _local(evaluator, objectives, checks, local_bounds, start, level.get('method', 'cobyla'), budget)
        best = _best(evaluator, objectives)
        centre = np.array([(best[1][item['path']] - b[0]) / (b[1] - b[0]) for item, b in zip(variables, bounds)])
        history += [{**h, 'evaluation': len(history) + i + 1} for i, h in enumerate(evaluator.history)]
        score = sum(o['weight'] * s for o, s in zip(objectives, _score(objectives, best[0]['record'])))
        summary.append({'level': evaluator.label, 'evaluations': len(evaluator.history), 'downstream': evaluator.downstream is not None,
                        'objective': score, **{item['path']: best[1][item['path']] for item in variables}})
    values = _finish(evaluator, best, variables, base_objectives, {'levels': float(len(levels)), 'evaluations': float(len(history))})
    notes = ['Multi-fidelity: each level optimises in a trust region around the previous optimum; '
             + '; '.join(f'{s["level"]} ({s["evaluations"]} evaluations{", downstream chain" if s["downstream"] else ""})' for s in summary)]
    return {'spec': best[0]['spec'], 'values': values,
            'history': {'kind': 'optimization', 'variables': [v['path'] for v in variables], 'objective': base_objectives[0]['expression'],
                        'sense': base_objectives[0]['sense'], 'method': 'multi_fidelity', 'rows': history, 'levels': summary},
            'notes': notes}
