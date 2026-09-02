# Third-party validation data

The Apache-2.0 license applies to Nova Propellers source code. Experimental
datasets, propeller geometries, airfoil data, manufacturer files,
publications, and other third-party reference material retain their respective
ownership and licensing terms and are not automatically covered by the
project's Apache-2.0 license. Third-party validation data is intentionally not
distributed with this repository.

Public download access is not treated as permission to redistribute. Where no
explicit license has been verified, Nova records `license: unspecified` and
`redistribution: not assumed`. This is a conservative project policy, not a
legal conclusion. Users remain responsible for complying with upstream terms
and citation requirements.

Raw reference inputs go under `backend/validation/reference_data/`, and
derived plots/reports under `backend/validation/generated/`. Both are ignored
by Git (except the explanatory marker README). Do not force-add them. Case
manifests contain URLs and provenance, but no copied measurements.

## UIUC and APC sources

Benchmark 1 uses the UIUC Propeller Database, Volume 1, version 3. The online
performance and approximate digitized geometry files are separate source
records even though UIUC publishes both. No explicit redistribution license
was found for either, so both remain local-only.

APC also publishes manufacturer geometry downloads for analysis. Availability
for analysis is not interpreted as redistribution permission; no APC file is
required by or included in Benchmark 1, and any future APC file must remain
local unless explicit permission is documented.

Citation used by the case manifest:

- Brandt, J. B. and Selig, M. S., “Propeller Performance Data at Low Reynolds
  Numbers,” AIAA Paper 2011-1255, 2011.
- UIUC Propeller Database, Volume 1, version 3, with access date and URL.

Authoritative upstream locations:

- <https://m-selig.ae.illinois.edu/props/propDB.html>
- <https://m-selig.ae.illinois.edu/props/volume-1/propDB-volume-1.html>
- <https://www.apcprop.com/technical-information/file-downloads/>

If an upstream statement or permission is later found, update the
machine-readable case provenance and this policy before changing how files are
distributed.
