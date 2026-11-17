# Verification and validation

## In brief

NOVA distinguishes **software verification** from **validation against physical measurements**.
Today BEMT passes the software verification; it is **not** experimentally validated and stays
labelled *preliminary*.

```{warning}
Passing the tests means a supported build reproduces the declared baseline and satisfies the
consistency checks. It does not mean a prediction is validated, certified, or safe to manufacture
or fly.
```

## In detail

### Evidence levels

:::{table} Evidence levels and current BEMT status
:name: tab-evidence

| Level | Question | Status |
|---|---|---|
| Contract verification | Is a result complete and unambiguous? | Implemented |
| Numerical regression | Did the code change unintentionally? | One baseline case |
| Physics consistency | Do outputs satisfy expected identities and trends? | Initial set |
| Reference validation | Does the solver agree with independent measurements? | Not implemented |
| Qualification | Is accuracy acceptable over a declared domain? | Not achieved |
:::

### The gated process

The gates are deliberately ordered: a comparison with measurements is meaningless until the software
produces traceable, consistent and reproducible results.

```{algorithm} Gated verification and validation process
:name: algorithm-vv

define the result contract: inputs, outputs, units, version, warnings, convergence
freeze deterministic regression cases
check physics and accounting invariants, such as $P = Q\,\Omega$
study numerical sensitivity: station count, tolerance, interpolation
compare with independent measurements over a whole operating range
qualify a bounded domain, with metrics declared in advance
```

{numref}`algorithm-vv` is cumulative: a later gate does not replace an earlier one. Agreement with
one experiment cannot excuse a violated power identity, and a stable regression case does not
demonstrate agreement with reality.

### Calibration, validation and held-out data

If empirical constants or corrections are introduced, the reference data are split by purpose:
**calibration** data may guide parameters, **validation** data measure the error once the choices
are frozen, and **held-out** data are not inspected during tuning and give the strongest protection
against overfitting. NOVA does not report an accuracy obtained by tuning and evaluating on the same
points without labelling it as calibration performance.

### Evidence records

Every validation case keeps its inputs, expected or measured outputs, units, provenance,
transformation notes and tolerances. The report also records the NOVA version, the result-schema
version, the solver configuration and the pass/fail criteria.

The full protocol and the reviewed results are in `VALIDATION.md` and
`verification/bemt-pre-experimental-verification.md` in the repository.
