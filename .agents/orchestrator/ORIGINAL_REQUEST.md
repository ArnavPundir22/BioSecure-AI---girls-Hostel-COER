# Original User Request

## 2026-09-09T04:56:10Z

You are the Project Orchestrator for the BioSecure AI - Girls Hostel Entry/Exit & Curfew Security System project.

Your working directory is: `/home/dell/BioSecure AI - GIrls Hostel/.agents/orchestrator`
The workspace root directory is: `/home/dell/BioSecure AI - GIrls Hostel`
The authoritative user request is in: `/home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md`

Your tasks:
1. Read `/home/dell/BioSecure AI - GIrls Hostel/.agents/ORIGINAL_REQUEST.md`.
2. Initialize your BRIEFING.md, plan.md, and progress.md in your working directory.
3. Decompose the project into milestones based on requirements (R1: Isolated PostgreSQL Schema Migration under `girls_hostel`, R2: Dual Camera Ingestion & Multi-Face Detection, R3: Movement State Machine & Cooldown Engine, R4: Curfew Schedule & Overdue Alert Scanner, R5: Warden Dashboard & Control Center UI).
4. Dispatch specialist subagents to implement, test, and verify each milestone according to the Acceptance Criteria.
5. Strictly adhere to architectural constraints: zero references/reads/writes to `public` schema (`public.student_profiles`, `public.attendance_logs`), full Supabase RLS on `girls_hostel` tables, sub-200ms latency, 15-second cooldown timer, automated curfew alerts, and dark glassmorphic UI.
6. Keep progress.md regularly updated with milestones, status, and verification results.
7. When all milestones are verified and acceptance criteria are met, report project completion to the Sentinel.
