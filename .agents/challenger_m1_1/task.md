# Challenger 1 Task — Stress-Test Schema Boundaries and Data Isolation

## Objective
Empirically stress-test the schema isolation, vector matching edge cases, and database contract bounds of Milestone 1.

## Scope & Target Deliverables
- `scripts/girls_hostel_schema.sql`
- `src/utils/hostel_db.py`
- `tests/unit/test_m1_schema_db.py`

## Challenge Areas
1. Stress-test data isolation: Attempt boundary violation tests, ensuring no table or query can cross over into `public`.
2. Vector matching boundary tests: Test extreme embeddings (orthogonal, identical, opposing, zero vector, NaN, malformed vector lengths) and threshold boundaries (0.0, 0.40, 1.0, >1.0).
3. Curfew alert concurrency & deduplication stress: Rapid concurrent or repeated insertions of alerts for the same student on the same date.
4. Run tests and write challenge scripts if needed to empirically verify behavior.
5. Provide handoff report in `.agents/challenger_m1_1/handoff.md`.
