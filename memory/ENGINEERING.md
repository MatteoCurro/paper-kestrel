# Product Engineering Memory

Last curated: 2026-10-08
Primary reader: Senior Product Engineer, Release Reviewer.

## Runtime shape

Public frontend is static HTML + vanilla JS.
The application is intentionally modular rather than framework-driven.

Important module families:
- `js/core/`: shared primitives/transport-state logic;
- `js/state/`: application state;
- `js/ui/`: shell/panel/presentation;
- `js/journey/`: journey planning/UI;
- `js/map/`: public-map behavior;
- `js/navigation/`: navigation and turn-by-turn;
- `js/driver/`: Driver Utility;
- `js/water/`: water-network logic;
- `js/identity/`: account/identity client;
- `js/analytics/`: analytics boundaries;
- provider adapters at `js/provider-*.js`.

## 9.0 refactor constraint

Current legacy UI responsibilities are split across older modules such as `js/ui/redesign.js`, app shell and Journey UI. The target is one authoritative navigation/panel lifecycle. Avoid adding another parallel navigation source of truth.

## Frontend rules

- preserve no-build browser compatibility;
- prefer small isolated modules;
- do not add framework dependencies casually;
- use existing project configuration rather than duplicating environment constants;
- user-facing strings must route through i18n IT/EN/FR/DE;
- do not expose service-role/server secrets in browser files.

## Testing

Repository has a broad deterministic Node/Python suite under `tests/`.
Use targeted tests first, then required aggregate checks.
Do not weaken unrelated tests to make a candidate pass.
Known baseline failures should be compared against unchanged baseline rather than silently ignored.

Account-focused tests cover foundation/onboarding/sync.
Navigation, routing, transit state, provider independence, ACTV normalization, alerts, entities, viewport, i18n and Driver Utility have dedicated tests.

## Change discipline

Inspect before editing.
Prefer smallest coherent diff.
Do not duplicate contracts already owned by a core module.
Persist candidate patch even when QA blocks it.

## Split-repository ownership

Public autonomous development is split:
- presentation/client repo owns root presentation pages, assets, locales and presentation-oriented JS;
- engine/data/test repo owns package/test/server/api/supabase/data/build/runtime-oriented code and non-presentation JS.

Private `u-venice-transport` remains the source/prod repository.

## Source pointers

- `README.md`
- `FOUNDATION-9.0-INVENTORY.md`
- `ARCHITECTURE-9.0-MASTER-PLAN.md`
- `package.json`
- `tests/run-r1.cjs`
