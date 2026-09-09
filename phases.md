# 📅 Implementation Roadmap & Phasing Plan (phases.md) — BioSecure AI: Girls Hostel System

## 1. Overview
This document outlines the 6 execution phases required to build, test, and deploy **BioSecure AI - Girls Hostel Edition**.

---

## 2. Master Implementation Phases

```mermaid
gantt
    title BioSecure AI — Girls Hostel System Implementation Phases
    dateFormat  YYYY-MM-DD
    section Phase 1: DB & Schema
    Phase 1: Isolated Schema Setup        :done, p1, 2026-09-09, 1d
    section Phase 2: Ingestion & AI
    Phase 2: Dual Camera Pipeline         :active, p2, 2026-09-10, 2d
    section Phase 3: State & Cooldown
    Phase 3: State Machine & Cooldown     :p3, 2026-09-12, 2d
    section Phase 4: Curfew & Alerts
    Phase 4: Overdue Alert Scanner       :p4, 2026-09-14, 2d
    section Phase 5: UI & Dashboard
    Phase 5: Warden Control Center UI     :p5, 2026-09-16, 2d
    section Phase 6: Testing & Launch
    Phase 6: E2E Verification & Launch    :p6, 2026-09-18, 2d
```

---

## 3. Phase-by-Phase Breakdown

### Phase 1: Isolated Database Schema Setup (`girls_hostel`)
- **Deliverables**:
  - `scripts/girls_hostel_schema.sql` migration script.
  - Creation of `girls_hostel` schema, `student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings` tables.
  - Deployment of `girls_hostel.match_face()` RPC function.
  - Verification that existing `public` schema tables remain completely untouched.

### Phase 2: Dual Camera Stream Ingestion & Multi-Face AI
- **Deliverables**:
  - `src/utils/hostel_camera.py`: Threaded stream ingestion manager supporting `CAM_01_ENTRY` and `CAM_02_EXIT`.
  - `src/utils/hostel_face.py`: InsightFace RetinaFace multi-face detector + ArcFace 512D feature extractor.
  - Live stream MJPEG generators for Entry and Exit feeds.

### Phase 3: Movement State Machine & Cooldown Logic
- **Deliverables**:
  - `src/utils/hostel_state.py`: State transition engine (`IN` $\leftrightarrow$ `OUT`).
  - Implementation of 15-second anti-bounce cooldown timer.
  - Automatic creation of movement log entries in `girls_hostel.movement_logs`.

### Phase 4: Curfew Monitoring & Overdue Alert Scanner
- **Deliverables**:
  - `src/services/curfew_service.py`: Background cron service checking curfew window (5:00 PM to 7:30 PM).
  - Automated detection of overdue `OUT` students at 7:30 PM.
  - Population of `girls_hostel.curfew_alerts` table.
  - Integration of SMTP Email alert dispatch to wardens and parents.

### Phase 5: Hostel Warden Dashboard & User Interface
- **Deliverables**:
  - `src/blueprints/hostel.py`: Flask blueprint registering `/hostel`, `/hostel/live`, `/hostel/overdue`, `/hostel/students`.
  - HTML5 / TailwindCSS dark glassmorphic interface (`src/templates/hostel_dashboard.html`).
  - Real-time movement log updates & visual overdue alert cards.

### Phase 6: System Verification & Acceptance Testing
- **Deliverables**:
  - E2E multi-student simulation test suite.
  - Verification of sub-200ms multi-face detection latency.
  - Verification of 100% database schema isolation.
  - Final production launch readiness review.
