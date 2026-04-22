# Contributing

## Adding a new feature view

This is the most common contribution. See `docs/FEATURE_AUTHORING.md` for the detailed walk-through.

Quick version:
1. Define the FeatureView in `src/feast_repo/feature_views/`
2. Register in `src/feast_repo/feature_views/__init__.py`
3. Author the compute (streaming in `src/lambdas/`, batch in `src/features/jobs/`)
4. Update the Terraform feature group definition in `modules/sagemaker_feature_store/`
5. `make test-unit && make validate-feature-views`
6. PR

## Adding a new source or sink

- New source: create `src/features/sources/my_source.py`, add to `__init__.py`
- New sink: create `src/features/sinks/my_sink.py` extending the base pattern, add to `__init__.py`
- Add unit test in `tests/unit/`

## Coding style

- Format with `make format` (ruff)
- Type hints on all public functions
- `structlog` via `get_logger`, not `print` or stdlib logging
- `from __future__ import annotations` on every Python file (already in all existing files)
- Pre-commit hooks run on `git commit`; install with `pre-commit install`

## Terraform

- Modules in `infra/terraform/modules/<n>/main.tf`
- No HCL semicolons
- `nonsensitive(toset(keys(...)))` pattern when `for_each` on sensitive vars
- `terraform fmt -recursive` before committing
- `terraform validate` must pass (CI gates this)

## PR checklist

- [ ] `make ci` green locally
- [ ] Unit tests for new code
- [ ] Docs updated if public API changed
- [ ] No secrets in diff (pre-commit checks)
- [ ] Terraform plan reviewed if infra changed
- [ ] Feature views pass `validate_feature_views.py`

## Questions

Open a GitHub Discussion or ping me on [LinkedIn](https://www.linkedin.com/in/sushmakl1995/).
