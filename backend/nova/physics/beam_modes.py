"""Bending modes of a clamped-free Euler–Bernoulli beam and their ElastoDyn polynomial form.

Finite elements with cubic Hermite shape functions and a consistent mass matrix; the distributions are
linear tables over the normalised length. ElastoDyn describes every mode shape as
φ(x) = c2 x² + c3 x³ + c4 x⁴ + c5 x⁵ + c6 x⁶ with c2 + … + c6 = 1, so the computed shape is fitted
with exactly that constraint and the fit error is reported.
"""
import numpy as np
from scipy.linalg import eigh

from nova.physics.modal import Beam

ELEMENTS = 80  # same discretisation as nova.physics.modal


def cantilever_modes(fraction, mass_per_length, stiffness, length_m, tip_mass_kg=0.0, modes=2, elements=ELEMENTS):
    """Natural frequencies (Hz) and unit-tip mode shapes sampled at the element nodes.

    `fraction`, `mass_per_length` (kg/m) and `stiffness` (N·m²) describe the distribution over 0–1 of the
    length. Returns (frequencies_hz, x, shapes) with shapes[mode] normalised to 1 at the free end.
    """
    if not 1 <= modes <= 4:
        raise ValueError('Between one and four modes can be computed')
    beam = Beam(fraction, mass_per_length, stiffness, length_m, elements)
    nodes = beam.nodes
    beam.add_point(1.0, mass=float(tip_mass_kg))
    size = beam.K.shape[0]
    free = slice(2, size)
    values, vectors = eigh(beam.K[free, free], beam.M[free, free], subset_by_index=[0, modes - 1])
    frequencies = np.sqrt(np.maximum(values, 0.0)) / (2 * np.pi)
    shapes = []
    for k in range(modes):
        w = np.concatenate([[0.0], vectors[0::2, k]])
        if abs(w[-1]) < 1e-12:
            raise ValueError('A computed mode has no tip displacement and cannot be normalised')
        shapes.append(w / w[-1])
    return frequencies, nodes, shapes


def polynomial_shape(x, shape):
    """Fit c2…c6 (summing to 1) to a mode shape; returns (coefficients, rms_error, max_error)."""
    x = np.asarray(x, dtype=float)
    shape = np.asarray(shape, dtype=float)
    basis = np.stack([x**k - x**6 for k in (2, 3, 4, 5)], axis=1)
    head, *_ = np.linalg.lstsq(basis, shape - x**6, rcond=None)
    coefficients = np.concatenate([head, [1.0 - head.sum()]])
    fitted = sum(c * x**k for c, k in zip(coefficients, (2, 3, 4, 5, 6)))
    error = fitted - shape
    return coefficients, float(np.sqrt(np.mean(error**2))), float(np.max(np.abs(error)))
