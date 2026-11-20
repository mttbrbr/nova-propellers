"""OpenFAST structural linearisation: case preparation, .lin parsing and multi-blade-coordinate eigenanalysis.

A flexible ElastoDyn case is turned into a structural linearisation (aerodynamics, inflow and gravity off,
prescribed rotor speed, linearisation times spread evenly over one revolution). The state matrices of the
.lin files are transformed to multi-blade coordinates and averaged over azimuth (MBC3, Bir 2008) — the same
procedure as Nova's own coupled Campbell diagram, so the two can be compared mode by mode.
"""
import re
from pathlib import Path

import numpy as np
from scipy.linalg import eig


class LinearizationError(ValueError):
    pass


ORDINAL = {'1st': 1, '2nd': 2, '3rd': 3}
FAMILIES = (('tower fore-aft', 'tower_fa'), ('tower side-to-side', 'tower_ss'), ('flapwise', 'blade_flap'),
            ('edgewise', 'blade_edge'), ('torsion', 'blade_torsion'))


# ------------------------------------------------------------------ case preparation

def _set(text, key, value):
    pattern = re.compile(rf'^(\s*)("[^"]*"|\S+)(\s+{re.escape(key)}\b)', re.M)
    if not pattern.search(text):
        raise LinearizationError(f'{key} not found in the OpenFAST input file')
    return pattern.sub(lambda m: f'{m[1]}{value}{m[3]}', text, count=1)


def _get(text, key):
    match = re.search(rf'^\s*("[^"]*"|\S+)\s+{re.escape(key)}\b', text, re.M)
    if not match:
        raise LinearizationError(f'{key} not found')
    return match[1].strip('"')


def prepare(directory, input_file, *, azimuths=12, settle_s=5.0, rpm=None):
    """Edit the .fst in `directory` for a structural linearisation; returns rotor speed (rpm) and linearisation times."""
    fst = Path(directory) / input_file
    text = fst.read_text()
    if _get(text, 'CompElast') != '1':
        raise LinearizationError('Linearisation needs a flexible ElastoDyn model (CompElast = 1): connect hub, nacelle, tower and '
                                 'blade structure to the OpenFAST case block')
    elastodyn = (fst.parent / _get(text, 'EDFile')).read_text()
    if rpm is None:
        rpm = float(_get(elastodyn, 'RotSpeed'))
    if _get(elastodyn, 'GenDOF').lower() in ('true', 't'):
        raise LinearizationError('The generator degree of freedom must be off (prescribed rotor speed)')
    if rpm <= 0:
        raise LinearizationError('Rotor speed must be positive for a periodic linearisation')
    period = 60.0 / rpm
    times = [settle_s + k * period / azimuths for k in range(azimuths)]
    dt = float(_get(text, 'DT'))
    for key, value in (('Linearize', 'True'), ('CalcSteady', 'False'), ('CompAero', '0'), ('CompInflow', '0'), ('CompServo', '0'),
                       ('Gravity', '0'), ('NLinTimes', str(azimuths)), ('LinInputs', '0'), ('LinOutputs', '0'),
                       ('TMax', f'{times[-1] + 2 * dt:.10g}'), ('WrVTK', '0')):
        text = _set(text, key, value)
    text, count = re.subn(r'^.*\bLinTimes\b.*$', ', '.join(f'{t:.10g}' for t in times) + '   LinTimes        - List of times at which to '
                          'linearize (s)', text, count=1, flags=re.M)
    if not count:
        raise LinearizationError('LinTimes not found in the OpenFAST input file')
    elastodyn_path = fst.parent / _get(text, 'EDFile')
    elastodyn = _set(elastodyn, 'RotSpeed', f'{rpm:.10g}')
    elastodyn_path.write_text(elastodyn)
    fst.write_text(text)
    return rpm, times


# ------------------------------------------------------------------ .lin files

def parse(text):
    lines = text.splitlines()

    def value(label):
        for line in lines:
            if line.strip().startswith(label):
                return float(line.split(':', 1)[1].split()[0])
        raise LinearizationError(f'{label} missing in .lin file')
    states = []
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith('Order of continuous states:')) + 3
    except StopIteration as exc:
        raise LinearizationError('No continuous states in the .lin file') from exc
    for line in lines[start:]:
        if not line.strip():
            break
        parts = line.split(None, 4)
        states.append({'operating_point': float(parts[1]), 'rotating': parts[2] == 'T', 'order': int(parts[3]),
                       'description': parts[4].strip()})
    n = len(states)
    try:
        at = next(i for i, line in enumerate(lines) if re.match(rf'^A:\s*{n}\s*x\s*{n}', line))
    except StopIteration as exc:
        raise LinearizationError('No A matrix in the .lin file') from exc
    A = np.array([[float(v) for v in lines[at + 1 + i].split()] for i in range(n)])
    return {'time_s': value('Simulation time'), 'omega': value('Rotor Speed'), 'azimuth': value('Azimuth'), 'states': states, 'A': A}


def _group(description):
    """Description without the blade number, and the blade number (None for fixed-frame states)."""
    description = re.sub(r'\s*\(internal DOF index[^)]*\)\)?', '', description)
    match = re.search(r' of blade (\d+)', description)
    if not match:
        return description, None
    return description[:match.start()] + ' of blade *' + description[match.end():], int(match[1])


def _family(description):
    text = description.lower()
    if 'first time derivative' in text:
        text = text.replace('first time derivative of ', '')
    family = next((name for key, name in FAMILIES if key in text), None)
    order = next((v for k, v in ORDINAL.items() if k in text), 1)
    return family, order


def mbc(files, blades):
    """Azimuth-averaged state matrix in multi-blade coordinates and the coordinate labels."""
    first = files[0]
    states = first['states']
    n2 = len(states)
    if n2 % 2 or any(s['order'] != 2 for s in states):
        raise LinearizationError('Only second-order (displacement + velocity) structural states are supported')
    n = n2 // 2
    displacement = states[:n]
    groups, labels, rows = {}, [], []
    for i, state in enumerate(displacement):
        key, blade = _group(state['description'])
        if blade is None:
            labels.append((state['description'], None))
            rows.append(('fixed', i))
        else:
            groups.setdefault(key, {})[blade] = i
    harmonics = ['0'] + [f'{h}{t}' for h in range(1, (blades - 1) // 2 + 1) for t in 'cs'] + (['d'] if blades % 2 == 0 else [])
    for key, members in groups.items():
        if sorted(members) != list(range(1, blades + 1)):
            raise LinearizationError(f'States of {key} are not present for every blade')
        for h in harmonics:
            labels.append((key, h))
            rows.append(('mbc', key, h))
    order = [r[1] for r in rows if r[0] == 'fixed'] + [members[b] for _, members in groups.items() for b in range(1, blades + 1)]
    if sorted(order) != list(range(n)):
        raise LinearizationError('Unexpected state layout in the .lin file')
    total = np.zeros((n2, n2))
    for item in files:
        if len(item['states']) != n2:
            raise LinearizationError('The .lin files have different state counts')
        psi, omega = item['azimuth'], item['omega']
        T, T1, T2 = (np.zeros((n, n)) for _ in range(3))
        for j, row in enumerate(rows):
            if row[0] == 'fixed':
                T[row[1], j] = 1.0
                continue
            _, key, h = row
            for b, index in groups[key].items():
                a = psi + 2 * np.pi * (b - 1) / blades
                if h == '0':
                    T[index, j] = 1.0
                elif h == 'd':
                    T[index, j] = (-1.0) ** (b - 1)
                else:
                    k = int(h[:-1])
                    if h.endswith('c'):
                        T[index, j], T1[index, j], T2[index, j] = np.cos(k * a), -k * np.sin(k * a), -k * k * np.cos(k * a)
                    else:
                        T[index, j], T1[index, j], T2[index, j] = np.sin(k * a), k * np.cos(k * a), -k * k * np.sin(k * a)
        Z = np.zeros((n, n))
        big = np.block([[T, Z], [omega * T1, T]])
        rate = omega * np.block([[T1, Z], [omega * T2, T1]])
        total += np.linalg.solve(big, item['A'] @ big - rate)
    return total / len(files), labels, harmonics


def modes(files, blades):
    """Fixed-frame modes of the averaged MBC system, labelled like Nova's coupled Campbell curves."""
    A, labels, harmonics = mbc(files, blades)
    n = len(labels)
    lam, vec = eig(A)
    keep = lam.imag > 1e-6
    lam, vec = lam[keep], vec[:n, keep]
    out = []
    for k in np.argsort(lam.imag):
        z = vec[:, k]
        energy = np.abs(z) ** 2
        energy = energy / max(energy.sum(), 1e-300)
        share = {}
        for weight, (description, h) in zip(energy, labels):
            family, number = _family(description)
            share[(family or description, number)] = share.get((family or description, number), 0.0) + float(weight)
        (family, number), _ = max(share.items(), key=lambda item: item[1])
        whirl = None
        if family and family.startswith('blade'):
            members = [i for i, (d, h) in enumerate(labels) if h is not None and _family(d) == (family, number)]
            power = {h: sum(energy[i] for i in members if labels[i][1] == h) for h in harmonics}
            cyclic = power.get('1c', 0.0) + power.get('1s', 0.0)
            if power['0'] >= cyclic and power['0'] >= power.get('d', 0.0):
                whirl = 'collective'
            elif power.get('d', 0.0) > cyclic:
                whirl = 'differential'
            else:
                c = np.array([z[i] for i in members if labels[i][1] == '1c'])
                s = np.array([z[i] for i in members if labels[i][1] == '1s'])
                whirl = 'forward' if np.imag(np.vdot(c, s)) < 0 else 'backward'
        out.append({'family': family, 'number': number, 'whirl': whirl, 'frequency_hz': float(lam[k].imag / (2 * np.pi)),
                    'natural_hz': float(abs(lam[k]) / (2 * np.pi)), 'damping_ratio': float(-lam[k].real / abs(lam[k]))})
    counts = {}
    for mode in out:
        base = mode['family'] + (f'_{mode["whirl"]}' if mode['whirl'] else '')
        counts[base] = counts.get(base, 0) + 1
        mode['id'] = f'{base}{counts[base]}'
    return out


def read_directory(directory, blades):
    files = sorted(Path(directory).glob('*.lin'), key=lambda p: int(re.search(r'\.(\d+)\.lin$', p.name)[1])
                   if re.search(r'\.(\d+)\.lin$', p.name) else 0)
    if not files:
        raise LinearizationError('OpenFAST wrote no .lin files')
    return [parse(p.read_text()) for p in files]


def compare(openfast_modes, nova_curves, rpm):
    """Pair OpenFAST modes with Nova's coupled curves at `rpm`: nearest frequency, preferring the same family and whirl
    (labels from state amplitudes are not reliable for higher tower modes, so frequency decides)."""
    from scipy.optimize import linear_sum_assignment
    nova = []
    for curve in nova_curves:
        frequency = float(np.interp(rpm, curve['rpm'], curve['frequency_hz']))
        nova.append({'id': curve['id'].removeprefix('coupled_'), 'frequency_hz': frequency, 'damping_ratio':
                     float(np.interp(rpm, curve['rpm'], curve['damping_ratio']))})
    if not nova or not openfast_modes:
        return []
    cost = np.array([[abs(o['frequency_hz'] - m['frequency_hz']) / max(m['frequency_hz'], 1e-9)
                      + (0.0 if o['id'] == m['id'] else 0.1) for m in nova] for o in openfast_modes])
    rows, cols = linear_sum_assignment(cost)
    pairs = []
    for r, c in zip(rows, cols):
        o, m = openfast_modes[r], nova[c]
        pairs.append({'openfast_mode': o['id'], 'nova_mode': m['id'], 'openfast_hz': o['frequency_hz'], 'nova_hz': m['frequency_hz'],
                      'difference_pct': (m['frequency_hz'] - o['frequency_hz']) / o['frequency_hz'] * 100,
                      'openfast_damping': o['damping_ratio'], 'nova_damping': m['damping_ratio']})
    return sorted(pairs, key=lambda p: p['openfast_hz'])
