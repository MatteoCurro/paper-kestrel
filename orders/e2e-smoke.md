# End-to-end smoke test

Status: approved.

Create exactly one new file:

tests/agent-orchestration-smoke.cjs

Requirements:
- use only Node.js built-in modules;
- contain one small deterministic assertion;
- print "agent orchestration smoke: ok" when run directly;
- do not modify any existing file.

Validation:
- run the new test directly with Node.js;
- run the existing full test suite;
- run git diff --check.

Delivery:
- open the normal review pull request;
- do not merge it.
