# Jarvis telemetry smoke v2

Status: approved.

Purpose: validate the canonical Agent Control Room telemetry path after schema consolidation.

Execution requirements:
- do not modify any repository file;
- create an empty work_items list;
- set use_solution_architect=false;
- set use_product_growth=false;
- set use_ui_ux=false;
- mandatory_checks must be exactly full_test and diff_check;
- perform the normal independent QA review;
- if the unchanged public validation workspace has the known baseline-equivalent test failure, treat the controller's baseline comparison as authoritative;
- do not open a pull request because there must be no code changes.

Success criteria:
- the workflow starts automatically from this committed order;
- Jarvis records the full lifecycle in agent_runs and agent_events;
- long checks expose started and completed events;
- run status ends as success/done;
- no target repository is modified.
