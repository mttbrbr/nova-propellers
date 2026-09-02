# BEMT pre-experimental verification report

Overall status: **PASS**

> Software and numerical verification in the declared domain; not validation against experimental measurements.

## Supported numerical domain

- solver: `bemt`
- operation: `static axial`
- minimum tolerance: `1e-05`
- maximum tangential induction ratio: `0.75`
- relaxation strategy: `fixed`
- relaxation factor: `0.08`
- low reynolds strategy: `clip`
- validated station counts: `[12, 18, 24, 36, 48, 72]`

## Evidence summary

- Golden regression: PASS
- Numerical sensitivity: PASS
- Root-induction selection: PASS
- Sensitivity evaluations: 90 matrix cases
- All sensitivity cases converged: True
- Maximum finest-grid relative error: 0.300291%
- Selected maximum tangential-induction ratio: 0.75

## Claim boundary

This report establishes deterministic behavior, internal physical consistency, declared convergence and numerical sensitivity. It does not establish predictive accuracy, certify a design or replace comparison with independent measurements.
