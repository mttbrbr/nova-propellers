"""3-D shell finite-element model of a blade for CalculiX (input deck writer and result parser).

The outer surface is lofted through the section outlines of the layup (chord, twist about the pitch
axis, airfoil-to-circle blend) and meshed with four-node shells (S4); the shear webs are shell strips
between the upper and lower surfaces. Every span band and region (shell, spar cap, web) gets its own
smeared isotropic material: the spar cap region is one shell of thickness t_shell + t_cap with the
thickness-weighted modulus and density (membrane-equivalent). The root section is clamped and a
*FREQUENCY step extracts the lowest natural frequencies (no rotation).
Coordinates: x along the span from the root, y in the rotor plane, z along the rotor axis.
"""
import math
import re

import numpy as np

from .section_properties import SectionError, outline


class ShellError(ValueError):
    pass


def _material_lines(name, E, G, rho):
    nu = min(max(E / (2 * G) - 1, 0.0), 0.49) if G > 0 else 0.3
    return [f'*MATERIAL, NAME={name}', '*ELASTIC', f'{E:.6e}, {nu:.4f}', '*DENSITY', f'{rho:.6e}']


def deck(layup, *, span_elements=30, perimeter_points=48, modes=10):
    """CalculiX input text for the layup produced by the blade_layup block, and a mesh summary."""
    stations = layup['stations']
    if len(stations) < 2:
        raise ShellError('The layup needs at least two stations')
    if not 4 <= span_elements <= 400 or not 12 <= perimeter_points <= 400 or not 1 <= modes <= 50:
        raise ShellError('span_elements 4–400, perimeter_points 12–400, modes 1–50')
    length = layup['length_m']
    fractions = np.array([s['fraction'] for s in stations])
    x_grid = np.linspace(0.0, 1.0, span_elements + 1)
    shell, cap, webs = layup['shell'], layup.get('spar_cap'), layup.get('webs') or []
    half = perimeter_points // 2
    nodes = []
    rings = []
    for i, x in enumerate(x_grid):
        chord = float(np.interp(x, fractions, [s['chord_m'] for s in stations]))
        twist = math.radians(float(np.interp(x, fractions, [s['twist_deg'] for s in stations])))
        blend = float(np.interp(x, fractions, [s['blend'] for s in stations]))
        try:
            upper, lower = outline(layup['airfoil'], blend, half + 1)
        except SectionError as exc:
            raise ShellError(str(exc)) from exc
        # closed loop: upper LE→TE then lower TE→LE (without repeating LE/TE when they coincide)
        loop = np.vstack([upper, lower[::-1][1:-1]])
        pitch_axis = layup.get('pitch_axis', 0.25)
        y = (loop[:, 0] - pitch_axis) * chord
        z = loop[:, 1] * chord
        c, s = math.cos(twist), math.sin(twist)
        ring = []
        for yy, zz, frac in zip(y, z, loop[:, 0]):
            nodes.append((x * length, yy * c - zz * s, yy * s + zz * c))
            ring.append(len(nodes))
        rings.append({'nodes': ring, 'chordwise': loop[:, 0], 'upper_count': len(upper), 'chord': chord, 'twist': twist,
                      'blend': blend, 'upper': upper, 'lower': lower})
    elements, sets = [], {}

    def add(set_name, quad):
        elements.append(quad)
        sets.setdefault(set_name, []).append(len(elements))
    bands = max(1, min(10, span_elements // 3))
    for i in range(span_elements):
        a, b = rings[i], rings[i + 1]
        band = min(int(i / span_elements * bands), bands - 1)
        n = len(a['nodes'])
        for k in range(n):
            k2 = (k + 1) % n
            chordwise = 0.5 * (a['chordwise'][k] + a['chordwise'][k2])
            region = 'CAP' if cap and abs(chordwise - cap['centre']) <= cap['width'] / 2 else 'SHELL'
            add(f'{region}{band}', (a['nodes'][k], a['nodes'][k2], b['nodes'][k2], b['nodes'][k]))
    # shear webs: strips between the upper and lower surface points nearest to the web position
    for j, web in enumerate(webs):
        divisions = 4
        strips = []
        for ring in rings:
            upper_index = int(np.argmin(np.abs(ring['upper'][:, 0] - web['position'])))
            lower_loop = ring['chordwise'][ring['upper_count']:]
            lower_index = ring['upper_count'] + int(np.argmin(np.abs(lower_loop - web['position'])))
            top, bottom = np.array(nodes[ring['nodes'][upper_index] - 1]), np.array(nodes[ring['nodes'][lower_index] - 1])
            column = [ring['nodes'][lower_index]]
            for d in range(1, divisions):
                nodes.append(tuple(bottom + (top - bottom) * d / divisions))
                column.append(len(nodes))
            column.append(ring['nodes'][upper_index])
            strips.append(column)
        for i in range(span_elements):
            band = min(int(i / span_elements * bands), bands - 1)
            for d in range(divisions):
                add(f'WEB{j}_{band}', (strips[i][d], strips[i][d + 1], strips[i + 1][d + 1], strips[i + 1][d]))
    lines = ['** Nova blade shell model (CalculiX)', '*NODE']
    lines += [f'{n}, {p[0]:.8e}, {p[1]:.8e}, {p[2]:.8e}' for n, p in enumerate(nodes, 1)]
    lines.append('*ELEMENT, TYPE=S4, ELSET=EALL')
    lines += [f'{e}, {q[0]}, {q[1]}, {q[2]}, {q[3]}' for e, q in enumerate(elements, 1)]
    for name, members in sets.items():
        lines.append(f'*ELSET, ELSET={name}')
        lines += [', '.join(str(m) for m in members[k:k + 16]) for k in range(0, len(members), 16)]
    lines.append('*NSET, NSET=ROOT')
    root = rings[0]['nodes']
    lines += [', '.join(str(m) for m in root[k:k + 16]) for k in range(0, len(root), 16)]
    for name in sets:
        band = int(re.search(r'(\d+)$', name)[1])
        x = (band + 0.5) / bands
        if name.startswith('SHELL'):
            E, G, rho, t = shell['E_pa'], shell['G_pa'], shell['density_kg_m3'], shell['thickness_m']
        elif name.startswith('CAP'):
            tc = float(np.interp(x, [0, 1], [cap['thickness_m'], cap.get('tip_thickness_m', cap['thickness_m'])]))
            t = shell['thickness_m'] + tc
            E = (shell['E_pa'] * shell['thickness_m'] + cap['E_pa'] * tc) / t
            G = (shell['G_pa'] * shell['thickness_m'] + cap['G_pa'] * tc) / t
            rho = (shell['density_kg_m3'] * shell['thickness_m'] + cap['density_kg_m3'] * tc) / t
        else:
            w = webs[int(re.match(r'WEB(\d+)_', name)[1])]
            E, G, rho, t = w['E_pa'], w['G_pa'], w['density_kg_m3'], w['thickness_m']
        lines += _material_lines(f'M_{name}', E, G, rho)
        lines += [f'*SHELL SECTION, ELSET={name}, MATERIAL=M_{name}', f'{t:.6e}']
    lines += ['*BOUNDARY', 'ROOT, 1, 6', '*STEP', '*FREQUENCY', f'{modes}', '*NODE FILE', 'U', '*END STEP']
    return '\n'.join(lines) + '\n', {'nodes': len(nodes), 'elements': len(elements), 'element_sets': len(sets)}


EIGEN = re.compile(r'E\s*I\s*G\s*E\s*N\s*V\s*A\s*L\s*U\s*E\s+O\s*U\s*T\s*P\s*U\s*T')
NUMBER = r'[-+]?\d*\.?\d+(?:[EeDd][-+]?\d+)?'


def frequencies(dat_text):
    """Natural frequencies (Hz) from the eigenvalue table of a CalculiX .dat file."""
    match = EIGEN.search(dat_text)
    if not match:
        raise ShellError('No eigenvalue output in the CalculiX .dat file')
    out = []
    for line in dat_text[match.end():].splitlines():
        tokens = line.split()
        if out and not tokens:
            break
        if len(tokens) >= 4 and tokens[0].isdigit() and all(re.fullmatch(NUMBER, t) for t in tokens[1:4]):
            out.append({'mode': int(tokens[0]), 'eigenvalue': float(tokens[1].replace('D', 'E')),
                        'frequency_hz': float(tokens[3].replace('D', 'E'))})
        elif out and not re.match(r'^\s*\d', line):
            break
    if not out:
        raise ShellError('Empty eigenvalue table in the CalculiX .dat file')
    return out
