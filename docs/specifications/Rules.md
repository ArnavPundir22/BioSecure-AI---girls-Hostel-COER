# 📜 System & Business Rules (Rules.md) — BioSecure AI: Girls Hostel System

## 1. Overview
This document defines the strict operational rules, business constraints, curfew enforcement policies, and database schema isolation rules governing **BioSecure AI - Girls Hostel Edition**.

---

## 2. Curfew & Schedule Enforcement Rules

### RULE-01: System Monitoring Window
- **Start Time**: Default `17:00` (5:00 PM local time).
- **Curfew Deadline / Last Allowed Entry**: Default `19:30` (7:30 PM local time).
- **Active Hours**: Curfew enforcement scans remain active continuously from `19:30` until `06:00` the following morning.

### RULE-02: Movement Classification & State Rules
- **State `IN`**: Student is confirmed to be inside the hostel premises.
- **State `OUT`**: Student has passed through `CAM_02_EXIT` and is outside the hostel.
- **Rule 02.1**: A student CANNOT transition to `OUT` if they are already recorded as `OUT` unless manually overridden by a hostel warden.
- **Rule 02.2**: A student returning through `CAM_01_ENTRY` transitions to `IN`, regardless of whether their return is on-time or overdue.

### RULE-03: Overdue Escalation Protocol
- **Level 1 (System Alert - 7:30 PM)**: At 7:30 PM, any student whose `current_status == 'OUT'` is automatically flagged as `OVERDUE_OUT`.
- **Level 2 (Dashboard Red Flag - 7:35 PM)**: Overdue students appear in the Hostel Warden Dashboard highlighted in high-visibility red cards.
- **Level 3 (Parent Notification - 7:45 PM)**: If the student has not returned by 7:45 PM (15 minutes grace period), automated SMS/Email dispatching sends an urgent curfew alert to the registered parent contact (`parent_contact`).

---

## 3. Database & Schema Isolation Rules

### RULE-04: Strict Schema Scoping
- **Rule 04.1**: All SQL queries, DDL scripts, RPC invocations, and ORM/Supabase table calls generated for the Girls Hostel project MUST explicitly specify the `girls_hostel` schema.
- **Rule 04.2**: Direct references to `public.student_profiles` or `public.attendance_logs` are STRICTLY BANNED in the hostel blueprint codebase.
- **Rule 04.3**: Database migrations MUST use schema prefixing (`CREATE TABLE girls_hostel.<table_name>`).

### RULE-05: Embedding Storage & RPC Isolation
- **Rule 05.1**: Face vector embeddings for hostel students MUST be stored exclusively in `girls_hostel.student_profiles`.
- **Rule 05.2**: The vector matching function MUST be invoked as `girls_hostel.match_face`.
- **Rule 05.3**: Cosine similarity cutoff for hostel face matches is locked at $\ge 0.40$.

---

## 4. Camera Ingestion & Cooldown Rules

### RULE-06: Anti-Bounce Cooldown Window
- **Rule 06.1**: To prevent multiple logs when a student stands in front of a camera lens, an anti-bounce timer of **15 seconds** per student per camera is enforced.
- **Rule 06.2**: Detection of the same student within 15 seconds on the same camera stream is silently ignored.

### RULE-07: Directional Camera Assignment
- **Rule 07.1**: `CAM_01_ENTRY` ONLY records `direction = 'IN'`.
- **Rule 07.2**: `CAM_02_EXIT` ONLY records `direction = 'OUT'`.
- **Rule 07.3**: Cross-directional detection (e.g. exiting student facing entry camera) is rejected based on camera ID scoping.

---

## 5. Security & Data Protection Rules

### RULE-08: Row Level Security (RLS) & Access Control
- **Rule 08.1**: RLS is enabled on all tables in `girls_hostel` schema.
- **Rule 08.2**: Anonymous public web requests (`anon` role) are strictly denied access to hostel student profiles or movement logs.
- **Rule 08.3**: Only authenticated hostel warden accounts (`role = 'hostel_warden'`) and backend service key connections are granted access.
