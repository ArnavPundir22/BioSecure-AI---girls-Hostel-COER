# Reviewer 1 Task — Milestone 1 Review

## Objective
Verify interface conformance, schema isolation, and correctness of Milestone 1 deliverables.

## Scope & Target Files
- `scripts/girls_hostel_schema.sql`
- `src/utils/hostel_db.py`
- `tests/unit/test_m1_schema_db.py`
- Reference: `/home/dell/BioSecure AI - GIrls Hostel/.agents/sub_orch_m1_schema/SCOPE.md`

## Verification Checks
1. Schema Isolation: Zero occurrences of `public.` or references to public tables.
2. RLS: Row level security enabled on all 4 tables with policies.
3. Vector Index & RPC: HNSW index on 512D ArcFace embeddings and match_face RPC definition.
4. Interface Conformance: All 15 required interface functions in `src/utils/hostel_db.py`.
5. Run tests: Run `./.venv/bin/pytest tests/unit/test_m1_schema_db.py -v` and check test execution and outputs.
6. Write handoff report in `.agents/reviewer_m1_1/handoff.md`.
