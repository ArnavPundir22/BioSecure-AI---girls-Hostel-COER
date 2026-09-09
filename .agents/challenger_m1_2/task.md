# Challenger 2 Task — Adversarial Stress-Testing & Integrity Verification

## Objective
Adversarially stress-test database contract edge cases, connection failure modes, and type handling in `src/utils/hostel_db.py` and `scripts/girls_hostel_schema.sql`.

## Scope & Target Deliverables
- `scripts/girls_hostel_schema.sql`
- `src/utils/hostel_db.py`
- `tests/unit/test_m1_schema_db.py`

## Challenge Areas
1. Database robustness under simulated failure: Simulate connection drops, invalid client injection, malformed responses.
2. High-volume stress testing: Test rapid creation of 500+ movement logs, retrieval with limits, order descending timestamp.
3. System settings tampering: Test injecting invalid types, deeply nested JSON, empty strings, SQL injection characters in keys.
4. Curfew alert resolution lifecycle: Multiple transitions (OVERDUE_OUT -> RESOLVED, EXCUSED, notes updating).
5. Run tests: `./.venv/bin/pytest tests/unit/test_m1_schema_db.py -v` and run adversarial test scripts.
6. Provide handoff report in `.agents/challenger_m1_2/handoff.md`.
