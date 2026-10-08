# Transit & Data Memory

Last curated: 2026-10-08
Primary reader: Transit/Data Specialist, Product Engineer for transport logic.

## ACTV official-source contract

Static GTFS:
- ACTV/AVM official land (`aut`);
- ACTV/AVM official navigation (`nav`).

Realtime:
- official ACTV GTFS-RT VehiclePositions and TripUpdates for both networks;
- same-origin transport through `api/actv-realtime.php`;
- proxy does not reinterpret payload;
- browser decoder/normalizer performs reconciliation.

Core files:
- `server/build_transit_data.py`;
- `api/actv-realtime.php`;
- `js/core/gtfs-rt.js`;
- `js/actv/realtime-normalizer.js`;
- `js/provider-actv.js`.

## Provider boundary

Application code consumes a provider-neutral contract through `UVTransitProvider`.
Avoid leaking ACTV-specific identifiers into generic Journey/Map/Navigation logic.

## Matching philosophy

Realtime `trip_id` cannot be assumed to equal current static GTFS IDs.
Wrong match is worse than temporarily omitting/weakening a vehicle.

Matching is evidence-based and conservative, using progressively weaker evidence such as:
- exact static trip;
- known physical-vehicle/trip correlation;
- stable logical aliases across publication generations;
- stop sequence/ordered stops;
- corrected timing;
- start time;
- route/direction compatibility;
- GPS/shape evidence only with ambiguity rejection.

Route-only vehicle retention is preferable to inventing headsign/shape/next stop when trip identity is uncertain.

Navigation network uses stricter fallbacks than automotive; dock proximity is not reliable trip progress evidence.

## Service-day

GTFS times can exceed 24:00.
Use Europe/Rome service-day-relative logic, not naive wall-clock matching.
Multiple static snapshots can remain valid for different dates.

## Canonical transit model

Keep separate:
- ServicePlan / TripInstance: expected scheduled service;
- observations: actual realtime evidence;
- TransitState: reconciliation.

TripInstance identity includes provider/network/service date/trip, not only trip_id.

A missing observation is not automatically a cancellation.

## Derived intelligence

Expected-position, delay estimation, anomaly/crowding/learning layers must preserve provenance/confidence and fail open.
Never train/derive truth from unverified model output recursively.

## Routing/navigation

Turn-by-turn is web-first and native-ready.
Walking + transit-assisted navigation must keep routing state/provider data modular.
Do not make map rendering the source of routing truth.

## Source pointers

- `ACTV-DIRECT-DATA.md`
- `TURN-BY-TURN-9.0-ARCHITECTURE.md`
- `NAVIGATION-FEASIBILITY.md`
- `SERVICE-ALERTS-ARCHITECTURE.md`
- `server/build_transit_data.py`
- `js/core/service-plan.js` / related core modules
