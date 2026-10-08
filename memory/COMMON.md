# Common Project Memory — U.Venice Transport

Last curated: 2026-10-08
Scope: every agent.

## Product identity

U.Venice Transport is the mobility layer of Unlock Venice, not a standalone demo. Production path: `/trasporti/`. Jarvis is only an observability/control surface for the engineering system.

Phase 9.0 source of truth: `ARCHITECTURE-9.0-MASTER-PLAN.md`.

The product is mobile-first and must remain usable without an account.

## Core architecture

Frontend:
- static HTML + vanilla JavaScript;
- no mandatory frontend build step;
- Leaflet for the public map;
- MapLibre + PMTiles for Driver Utility;
- i18n catalogs in IT/EN/FR/DE;
- PHP kept minimal for same-origin/server endpoints.

Runtime transit data:
- generated separately from frontend deploy;
- published under `/trasporti/runtime-data/`;
- frontend deploy must not delete or overwrite that lifecycle.

Transit core:
- official ACTV/AVM static GTFS for land `aut` and water `nav`;
- official ACTV GTFS-RT through minimal same-origin proxy;
- protobuf decoded locally;
- conservative reconciliation of realtime/static identifiers;
- application-facing provider boundary is `UVTransitProvider`.

## 9.0 information architecture

Top-level product domains:
- MAP / map exploration;
- JOURNEY / A→B planning;
- PROFILE / persistence, account and preferences.

Mobile presentation has two primary patterns:
- full-screen workspace for complex tasks;
- context card/bottom sheet for selected map objects.

A feature does not earn a new top-level control merely because it exists.

Navigation/panel lifecycle is moving toward one authoritative manager. Avoid duplicating drawer/panel/back/viewport state in feature modules.

## Stable entity principles

Displayed names are never primary identifiers.
Entities use stable IDs and localized names.
HTTPS URLs/deep links are canonical; web remains native-ready.

## i18n

Core languages: IT, EN, FR, DE.
New user-facing functionality must not introduce untranslated hardcoded UI strings.
Tests should preserve key parity.

## Account principle

No login wall for core mobility use.
Account is optional and introduced where it adds value such as saved items, synchronization, notifications or continuity.

## Data/intelligence principle

Expected service and observed service remain separate.
Do not equate missing realtime observation with cancellation.
Derived/ML/intelligence layers are optional, fail-open consumers of canonical transit state and never overwrite ground truth.

## Reuse principle

Prefer small, license-compatible open-source components behind U.Venice adapters. Avoid importing large frameworks to solve narrow problems.

## Testing/release

Before production merge, relevant work must preserve:
- automated suite;
- routing/realtime behavior;
- i18n;
- mobile/iPhone behavior where affected;
- keyboard/viewport/back behavior where affected;
- master-plan/documentation coherence when architecture changes.

## Key authoritative documents

- `ARCHITECTURE-9.0-MASTER-PLAN.md`
- `FOUNDATION-9.0-INVENTORY.md`
- `HANDOFF.md`
- `ACTV-DIRECT-DATA.md`
- `TURN-BY-TURN-9.0-ARCHITECTURE.md`
- `IDENTITY-9.0-ARCHITECTURE.md`
- `M10-DATA-PRIVACY-ARCHITECTURE.md`
- `SERVICE-ALERTS-ARCHITECTURE.md`
- `DEPLOYMENT.md`

If a memory entry conflicts with one of these documents, the authoritative document wins and memory must be corrected after the accepted change.
