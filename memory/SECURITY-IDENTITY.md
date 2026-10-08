# Security, Identity & Privacy Memory

Last curated: 2026-10-08
Primary reader: Security/Privacy Specialist, Product Engineer for account/auth work.

## Account principle

Core mobility is guest-accessible.
Account is optional and used for durable personal value.

## Current account architecture

Supabase is the account/data backend for the T-Sand account implementation.

Browser security rules:
- publishable/public key only in browser;
- service-role/secret never in frontend;
- RLS is authoritative;
- authenticated user can access only owned rows;
- no admin role derived from user-editable profile fields.

## Auth

Current project email template emits a numeric OTP.
Operational browser flow:
1. email;
2. `signInWithOtp` with `shouldCreateUser:false` where account creation is not intended;
3. code entry;
4. `verifyOtp({ email, token, type:'email' })`.

Do not casually change the global email template because registration/login flows share it.

OAuth is separate from the Supabase dashboard login and requires explicit project Auth provider configuration/linking.

## Session

The security architecture intentionally avoids pretending persistent session behavior exists when infrastructure does not support it.

Tokens must not be copied into analytics, logs, URLs or arbitrary browser storage.
Sign-out must stop sync and clear account-scoped client data.

## Personal data

Saved home/work and similar places are personal data.
Mapping/geocoder/routing providers may still receive network/query/coordinate information even if U.Venice does not persist it.

## Consent

Marketing email and personalization are separate choices.
No preselected marketing.
Notification preferences and marketing consent should remain separate concerns.

## Account data

Account-owned saved data is remote-first when account service is active.
No automatic merge of old guest data into accounts.
Sync writes require enabled sync contract.
Export/delete paths must use authenticated ownership and allowlists.

## RLS expectations

- RLS on exposed personal-data tables;
- anon no personal-row privileges;
- `(select auth.uid()) = user_id`-style ownership for authenticated operations;
- ownership cannot be changed through update;
- delete/export must remain possible for owner;
- service-role only in managed backend.

## Source pointers

- `IDENTITY-9.0-ARCHITECTURE.md`
- `M10-DATA-PRIVACY-ARCHITECTURE.md`
- `ACCOUNT-9.0-ARCHITECTURE.md`
- `ACCOUNT-ONBOARDING-IMPLEMENTATION.md`
- `ACCOUNT-SYNC-IMPLEMENTATION.md`
- `config/account.json`
- `js/identity/`
