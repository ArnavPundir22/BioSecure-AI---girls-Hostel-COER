# Reviewer 2 Task — Milestone 1 Review

## Objective
Independent adversarial and robustness review of Milestone 1 deliverables.

## Scope & Target Files
- `scripts/girls_hostel_schema.sql`
- `src/utils/hostel_db.py`
- `tests/unit/test_m1_schema_db.py`
- Reference: `/home/dell/BioSecure AI - GIrls Hostel/.agents/sub_orch_m1_schema/SCOPE.md`

## Verification Checks
1. Code quality, security, and edge-case handling in `src/utils/hostel_db.py`.
2. Schema Isolation: Check that no queries can accidentally leak or join against `public` schema.
3. RLS and Security: Inspect RLS policies and ensure service_role isolation.
4. Test execution: Run `./.venv/bin/pytest tests/unit/test_m1_schema_db.py -v` and verify coverage and assertions.
5. Provide report in `.agents/reviewer_m1_2/handoff.md`.
