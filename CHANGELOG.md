# Changelog

## [Unreleased]

### Added
- Initial design package: README, roadmap (epics + spikes), pipeline
  architecture (4 phases / 11 stages), target event model, skills system,
  validation ladder, harness security model.
- Artifact JSON Schemas: surface map (S1), gap model (S3), implementation DTO (S8).
- First skill draft: s1-surface-mapper (disambiguation role).
- Packaging: `oah` installable via `pip install oah`; `.github/workflows/publish-pypi.yml`
  publishes to PyPI via Trusted Publishing (OIDC) on a `v*` tag push.
