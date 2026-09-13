# Changelog

## [0.3.2] - 2026-09-13

### Added

- hassfest CI (home-assistant/actions/hassfest@master)
- HACS validate CI (hacs/action@main)
- tag-triggered auto Release workflow
- PR template + Issue template

### Fixed

- manifest: remove deprecated keys (authors/icon/homeassistant)
- manifest: canonical key order (domain, name, then alphabetical)
- services.yaml: remove deprecated device target filters
- .gitignore: allow CHANGELOG.md and PR template (were excluded by `*.md`)

## [0.3.1] - 2026-07-11

- Full Chinese localization (README + HA UI translations)
- services.yaml cleanup
