# Contributing

Nova welcomes focused bug reports, validation cases and small reviewed pull
requests. Discuss large features in an issue before implementation.

## Development checks

Before opening a pull request, run:

```bash
python tools/check_licenses.py
python tools/check_source_archive.py
docker compose run --rm --no-deps backend python -m unittest discover -s tests -v
docker compose run --rm --no-deps frontend npm run lint
docker compose run --rm --no-deps frontend npm run build
```

## Provenance requirements

- Do not submit copied code, datasets or media without recording their source
  and redistribution license.
- New dependencies require an updated lockfile and third-party notice review.
- Experimental measurements require provenance, units, uncertainty and a
  license that permits repository redistribution.
- Generated media must not contain unlicensed music, fonts, logos or stock
  assets.

Unless explicitly stated otherwise, intentionally submitted contributions are
licensed under Apache-2.0 as described in section 5 of that license.
