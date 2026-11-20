"""DUST (mid-fidelity vortex-particle solver, Politecnico di Milano, MIT licence) case writer and load reader.

Nova writes a self-contained DUST case for a horizontal-axis rotor: one parametric lifting-line blade
component (``ElType = l``) multiplied into a rotor by a rotating reference frame, the airfoil tables in
C81 format tabulated from Nova's own polars at each section, the solver settings and an
``integral_loads`` post-processing analysis of the rotor in the global frame. Input syntax follows the
DUST example cases (``examples/robin``) and the C81 reader ``src/io/mod_c81.f90``.

Frame: the rotor axis is global z, the free stream blows along +z, blades start along +y and rotate about
+z (a blade at +y moves towards −x). Sections have the chord along x with the leading edge towards −x
(reference point at the pitch-axis chord fraction). DUST's twist rotates the section nose-up about the
span axis, which raises the incidence of this inflow, so a turbine twist θ (that lowers it) is written as −θ.
"""
import math

import numpy as np


class DustError(ValueError):
    pass


def c81(name, polar, *, reynolds, radius=None, machs=(0.0, 0.9)):
    """C81 table (cl, cd, cm vs α and Mach) of a Nova polar at one Reynolds number; cm is zero (not modelled)."""
    # the C81 counts are two-digit fields: 1° steps in the working range, 10° outside (91 angles)
    alpha = np.concatenate([np.arange(-180.0, -30.0, 10.0), np.arange(-30.0, 30.01, 1.0), np.arange(40.0, 180.01, 10.0)])
    if radius is None:
        cl, cd = polar(alpha, reynolds)
    else:
        cl, cd = polar(alpha, np.full_like(alpha, reynolds), np.full_like(alpha, radius))
    cl, cd = np.asarray(cl), np.asarray(cd)
    if len(alpha) > 99 or len(machs) > 99:
        raise DustError('C81 tables hold at most 99 angles and Mach numbers')
    counts = ''.join(f'{v:02d}' for v in (len(machs), len(alpha)) * 3)
    lines = ['1 0 0', '0 1', '0.158 0.158', 'COMMENT#1', f'{reynolds:14.1f}    0.200', f'{name[:30]:<30}{counts}']
    header = ''.join(f'{m:11.3f}' for m in machs)
    for values in (cl, cd, np.zeros_like(cl)):
        lines.append(' ' * 7 + header)
        lines += [f'{a:8.2f}' + ''.join(f'{v:11.5f}' for v in [c] * len(machs)) for a, c in zip(alpha, values)]
    return '\n'.join(lines) + '\n'


def write(directory, rotor, polar, *, velocity, rpm, pitch_axis=0.25, sections=9, nelem_span=24, revolutions=4,
          steps_per_revolution=48, particles=60000, vortex_radius=None, kinematic_viscosity=1.5e-5):
    """Write the case files into `directory`; returns the file names and the time window of the last revolution."""
    hub, tip = float(rotor.hub_radius_m), float(rotor.tip_radius_m)
    blades = int(rotor.blades)
    if blades < 1 or not tip > hub >= 0:
        raise DustError('Invalid rotor geometry')
    radius = np.asarray(rotor.radius_m)
    r = np.linspace(hub, tip, sections)
    chord = np.interp(r, radius, rotor.chord_m)
    twist = np.interp(r, radius, np.asarray(rotor.twist_deg)) + float(rotor.pitch_deg)
    omega = rpm * math.pi / 30
    files = {}
    blade = ['MeshFileType = parametric', 'ElType = l', '', f'starting_point = (/0.0, {hub:.6f}, 0.0/)',
             f'reference_chord_fraction = {pitch_axis:.4f}', '']
    for k in range(sections):
        reynolds = max(1e4, chord[k] * math.hypot(velocity, omega * r[k]) / kinematic_viscosity)
        table = f'airfoil_{k + 1:02d}.c81'
        files[table] = c81(f'nova{k + 1:02d}', polar, reynolds=reynolds, radius=r[k] if hasattr(polar, 'polars') else None)
        blade += [f'! section {k + 1}: r = {r[k]:.4f} m', f'chord = {chord[k]:.6f}', f'twist = {-twist[k]:.6f}',
                  f'airfoil_table = ./{table}', '']
        if k < sections - 1:
            span = r[k + 1] - r[k]
            count = max(1, round(nelem_span * span / (tip - hub)))
            blade += [f'span = {span:.6f}', 'sweep = 0.0', 'dihed = 0.0', f'nelem_span = {count}', 'type_span = uniform', '']
    files['blade.in'] = '\n'.join(blade) + '\n'
    files['References.in'] = '\n'.join([
        'Reference_Tag = Hub', 'Parent_Tag = 0', 'Origin = (/0.0, 0.0, 0.0/)', 'Orientation = (/1.0,0.0,0.0, 0.0,1.0,0.0, 0.0,0.0,1.0/)',
        'Multiple = T', 'Moving = F', '', 'Multiplicity = {', '  MultType = rotor', f'  N_Blades = {blades}', '  Rot_Axis = (/0.0, 0.0, 1.0/)',
        f'  Rot_Rate = {omega:.8f}', '  Psi_0 = 0.0', '  Hub_Offset = 0.0', '  N_dofs = 0', '}', ''])
    files['dust_pre.in'] = 'CompName = Rotor\nGeoFile = blade.in\nRefTag = Hub\n\nFileName = ./geo_input.h5\n'
    period = 2 * math.pi / omega
    dt = period / steps_per_revolution
    tend = revolutions * period
    box = 2.5 * tip + revolutions * period * velocity
    core = vortex_radius if vortex_radius is not None else 0.05 * float(np.mean(chord))
    files['dust.in'] = '\n'.join([
        'basename = ./Output/nova', f'u_inf = (/ 0.0, 0.0, {velocity:.6f} /)', '',
        'tstart = 0.0', f'tend = {tend:.8f}', f'dt = {dt:.8f}', f'dt_out = {dt:.8f}', 'output_start = T', '',
        'GeometryFile = geo_input.h5', 'ReferenceFile = ./References.in', '',
        f'VortexRad = {core:.6f}', 'FMM = T', 'Vortstretch = T', 'Diffusion = T', 'PenetrationAvoidance = F', '',
        'n_wake_panels = 1', f'n_wake_particles = {particles}',
        f'particles_box_min = (/ {-1.5 * tip:.4f}, {-1.5 * tip:.4f}, {-0.5 * tip:.4f}/)',
        f'particles_box_max = (/ {1.5 * tip:.4f}, {1.5 * tip:.4f}, {box:.4f}/)', '',
        f'BoxLength = {3 * tip:.4f}', f'NBox = (/1,1,{max(1, math.ceil((box + 0.5 * tip) / (3 * tip)))}/)',
        f'OctreeOrigin = (/{-1.5 * tip:.4f}, {-1.5 * tip:.4f}, {-0.5 * tip:.4f}/)', 'NOctreeLevels = 6', 'MinOctreePart = 5',
        'MultipoleDegree = 2', '', 'LLtol = 1.0e-4', 'LLdamp = 5.0', ''])
    steps = int(round(tend / dt))
    files['dust_post.in'] = '\n'.join([
        'data_basename = ./Output/nova', 'basename = ./Postpro/nova', '', 'Analysis = {', 'Type = integral_loads', 'Name = loads_rotor',
        'StartRes = 1', f'EndRes = {steps}', 'StepRes = 1', 'Format = dat', 'Component = Rotor', 'Reference_Tag = 0', '}', ''])
    for name, text in files.items():
        (directory / name).write_text(text)
    (directory / 'Output').mkdir(exist_ok=True)
    (directory / 'Postpro').mkdir(exist_ok=True)
    return {'files': sorted(files), 'period_s': period, 'last_revolution': (tend - period, tend), 'time_step_s': dt,
            'loads_file': 'Postpro/nova_loads_rotor.dat'}


def read_loads(text):
    """Rows of the integral-loads .dat file: t, Fx, Fy, Fz, Mx, My, Mz (global frame)."""
    rows = []
    for line in text.splitlines():
        tokens = line.split()
        if len(tokens) < 7 or line.lstrip().startswith('#'):
            continue
        try:
            values = [float(t) for t in tokens[:7]]
        except ValueError:
            continue
        rows.append(values)
    if not rows:
        raise DustError('No load samples in the DUST integral-loads file')
    return np.array(rows)


def rotor_performance(loads, *, window, omega, velocity, density, tip_radius):
    """Mean thrust, torque, power and coefficients over a time window."""
    t = loads[:, 0]
    keep = (t >= window[0] - 1e-9) & (t <= window[1] + 1e-9)
    if keep.sum() < 2:
        raise DustError('Too few load samples in the last revolution')
    thrust, torque = float(loads[keep, 3].mean()), float(loads[keep, 6].mean())
    area = math.pi * tip_radius**2
    power = torque * omega
    q = 0.5 * density * velocity**2
    return {'thrust_n': thrust, 'torque_nm': torque, 'power_w': power, 'CT': thrust / (q * area),
            'CP': power / (q * area * velocity), 'samples': int(keep.sum())}
