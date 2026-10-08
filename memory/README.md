# Project Memory

This directory is the persistent operational memory for autonomous U.Venice Transport engineering.

It is deliberately repository-backed rather than free-form model memory.

## Rules

- `COMMON.md` is read by every role before planning or implementation.
- The orchestrator loads one or more domain memories relevant to the assigned work.
- `DECISIONS.md` contains accepted architectural/product decisions only.
- Run-local discoveries belong in the Progress Ledger / handoff board first.
- A failed or unapproved run must not silently rewrite persistent project memory.
- Persistent memory is updated only when:
  1. an accepted change modifies architecture/behavior; or
  2. the owner/manager explicitly corrects a durable project fact.
- Memory entries should point to authoritative repository documents/files where possible.
- Master plans remain authoritative when memory conflicts with them.
- Keep memory compact: record contracts, ownership, invariants, pitfalls and current state; do not duplicate whole source files.

## Memory scopes

- `COMMON.md`: product/architecture map every role needs.
- `PRODUCT-UX.md`: interaction architecture and product principles.
- `ENGINEERING.md`: frontend/runtime/module/test conventions.
- `TRANSIT-DATA.md`: GTFS/GTFS-RT, provider contracts, routing/data layers.
- `SECURITY-IDENTITY.md`: account, Auth, RLS, privacy and consent.
- `INFRASTRUCTURE.md`: deploy, Gandi, runtime-data lifecycle, CI boundaries.
- `GROWTH-SEO.md`: SEO, editorial integration, analytics/attribution.
- `DECISIONS.md`: compact durable decision log.

Source of truth for phase 9.0: `ARCHITECTURE-9.0-MASTER-PLAN.md` in the private source repository.
