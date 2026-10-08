# Product & UX Memory

Last curated: 2026-10-08
Primary reader: Product & UX Critic, Product Engineer for user-facing work, Release Reviewer.

## Product direction

The app should feel simple even when the transport/data stack is complex.

Every feature must fit one of:
- Map;
- Journey;
- Profile.

Avoid new first-level buttons unless the master plan changes the information architecture.

## Mobile contract

Complex tasks use full-screen workspace.
Selected stop/vehicle/POI context uses lightweight context cards.

Do not reintroduce arbitrary intermediate panel heights for major tasks.

Account/profile, saved items, alerts, line selection, journey search/results and settings are full-height task surfaces on mobile.

## Navigation

The long-term architecture has one Navigation/Panel Manager responsible for:
- open/close;
- back target/history;
- focus;
- keyboard/visual viewport;
- scroll locking;
- aria state;
- desktop/mobile presentation.

Feature modules should request navigation transitions rather than directly reimplement drawer state.

## Critic behavior

The Product & UX Critic must inspect the existing product and challenge the proposal, not merely validate CSS.

For each user-facing change ask:
- Is this the simplest useful interaction?
- Does it duplicate another feature/entry point?
- Is the hierarchy aligned with Map/Journey/Profile?
- Is it understandable to a tourist without domain knowledge?
- Does it work on a narrow phone without losing primary actions?
- Does it degrade gracefully when realtime/provider/account capabilities are absent?
- Could the same goal be achieved with less UI?

Feedback must be classified as:
- blocker: user/product contract materially fails;
- suggestion: better but not required for release.

## Account UX

Registration/login must be clear, separate entry points.
Account should be a meaningful user space, not a thin auth form.
Do not repeatedly discourage optional profile completion; optional data should be requested only where it adds visible value.

Core transport remains guest-accessible.

## Driver Utility

Driver tools are a distinct operational mode and should not leak into passenger IA.
Driver map/navigation can be immersive and uses MapLibre/PMTiles.

## Accessibility

Interactive targets should be touch-friendly.
Focus/back/keyboard behavior matters as much as visual layout.
Color must not be the sole status signal.
Reduced-motion preferences should be respected where motion exists.

## Source pointers

- `ARCHITECTURE-9.0-MASTER-PLAN.md` sections IA / Panel Manager
- `DESIGN-SPEC-ROADMAP.md`
- `FOUNDATION-9.0-INVENTORY.md`
- `ACCOUNT-9.0-ARCHITECTURE.md`
- `DRIVER-MAP-PLAN.md`
