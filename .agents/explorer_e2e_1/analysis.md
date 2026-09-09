# E2E Test Architecture Analysis: R1 & R2 Focus
**Author**: Explorer 1 (E2E Test Architecture)  
**Date**: 2026-09-09  
**Target Scope**: Requirement 1 (Isolated PostgreSQL Schema Migration) & Requirement 2 (Dual Camera Ingestion & Multi-Face Detection)

---

## Executive Summary
This document defines the opaque-box test strategy, test case specifications (Tier 1 Feature Coverage and Tier 2 Boundary/Corner Cases), and test fixture/mock boundaries for:
1. **R1: Isolated PostgreSQL Schema Migration (`girls_hostel`)**: Guaranteeing 100% data and operational isolation, Row Level Security (RLS) across all tables, HNSW vector indexing, the `girls_hostel.match_face` RPC function signature and mathematical correctness, and zero leakage to/from the `public` schema.
2. **R2: Dual Camera Ingestion & Multi-Face Detection**: Ingesting simultaneous video streams for Camera 1 (Entry Gate) and Camera 2 (Exit Gate), detecting and extracting up to 10 faces concurrently using InsightFace (RetinaFace + ArcFace 512D), validating the <200ms frame batch processing SLA, and enforcing 512D unit-norm embedding integrity.

---

## 1. Deep-Dive Analysis: Requirement R1 (Schema Isolation & Vector RPC)

### 1.1 Architectural Boundary & Schema Specification
The `girls_hostel` subsystem must operate as a completely autonomous, sandboxed schema within PostgreSQL. 
The canonical DDL in `scripts/girls_hostel_schema.sql` defines:
- **Schema**: `CREATE SCHEMA IF NOT EXISTS girls_hostel;`
- **Tables**:
  1. `girls_hostel.student_profiles`:
     - `id UUID PRIMARY KEY DEFAULT gen_random_uuid()`
     - `name VARCHAR(255) NOT NULL`
     - `roll_number VARCHAR(100) UNIQUE NOT NULL`
     - `room_number VARCHAR(50) NOT NULL`
     - `hostel_block VARCHAR(50) DEFAULT 'Block-A'`
     - `parent_contact VARCHAR(20) NOT NULL`
     - `student_contact VARCHAR(20)`
     - `embedding VECTOR(512)`
     - `current_status VARCHAR(20) DEFAULT 'IN'` (Restricted to `'IN'` or `'OUT'`)
     - `last_movement_time TIMESTAMP WITH TIME ZONE`
     - `current_ewma_drift FLOAT DEFAULT 0.0`
     - `drift_alert_level VARCHAR(50) DEFAULT 'HEALTHY'`
     - `created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
  2. `girls_hostel.movement_logs`:
     - `id BIGSERIAL PRIMARY KEY`
     - `student_id UUID NOT NULL REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE`
     - `direction VARCHAR(10) NOT NULL` (`'IN'` or `'OUT'`)
     - `camera_id VARCHAR(50) NOT NULL` (`'CAM_01_ENTRY'` or `'CAM_02_EXIT'`)
     - `timestamp TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
     - `confidence FLOAT DEFAULT 1.0`
     - `snapshot_url TEXT`
     - Index: `idx_girls_hostel_movement_student_time ON girls_hostel.movement_logs (student_id, timestamp DESC)`
  3. `girls_hostel.curfew_alerts`:
     - `id BIGSERIAL PRIMARY KEY`
     - `student_id UUID NOT NULL REFERENCES girls_hostel.student_profiles(id) ON DELETE CASCADE`
     - `curfew_date DATE DEFAULT CURRENT_DATE`
     - `system_start_time TIME DEFAULT '17:00:00'`
     - `curfew_end_time TIME DEFAULT '19:30:00'`
     - `status VARCHAR(30) DEFAULT 'OVERDUE_OUT'` (`'OVERDUE_OUT'`, `'RESOLVED'`, `'EXCUSED'`)
     - `alert_triggered_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
     - `resolved_at TIMESTAMP WITH TIME ZONE`
     - `notes TEXT`
     - Index: `idx_girls_hostel_curfew_status ON girls_hostel.curfew_alerts (status, curfew_date)`
  4. `girls_hostel.system_settings`:
     - `key VARCHAR(100) PRIMARY KEY`
     - `value JSONB NOT NULL`
     - `updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP`
     - Default rows: `curfew_schedule`, `camera_sources`, `alert_config`.

### 1.2 Row Level Security (RLS) & Access Control
- **Mandatory DDL requirement**:
  ```sql
  ALTER TABLE girls_hostel.student_profiles ENABLE ROW LEVEL SECURITY;
  ALTER TABLE girls_hostel.movement_logs ENABLE ROW LEVEL SECURITY;
  ALTER TABLE girls_hostel.curfew_alerts ENABLE ROW LEVEL SECURITY;
  ALTER TABLE girls_hostel.system_settings ENABLE ROW LEVEL SECURITY;
  ```
- **Policy Requirements**:
  - `service_role` has full CRUD permissions across all 4 tables.
  - Anonymous/unauthenticated roles have ZERO read/write access without explicit permissive policies.
  - Test validation must inspect both the SQL DDL commands and the client execution behavior under anon vs service-role identities.

### 1.3 HNSW Vector Indexing
- Table `girls_hostel.student_profiles` contains the 512D ArcFace facial embedding vector.
- Vector index declaration:
  ```sql
  CREATE INDEX IF NOT EXISTS idx_girls_hostel_students_embedding
  ON girls_hostel.student_profiles 
  USING hnsw (embedding vector_cosine_ops);
  ```
- Operator class `vector_cosine_ops` matches cosine distance operator `<=>`.

### 1.4 Vector Matching RPC (`girls_hostel.match_face`)
- **Signature**:
  ```sql
  CREATE OR REPLACE FUNCTION girls_hostel.match_face(
      query_embedding VECTOR(512),
      match_threshold FLOAT DEFAULT 0.40,
      match_count INT DEFAULT 1
  )
  RETURNS TABLE (
      id UUID,
      name VARCHAR(255),
      roll_number VARCHAR(100),
      room_number VARCHAR(50),
      current_status VARCHAR(20),
      similarity FLOAT
  )
  LANGUAGE plpgsql
  SECURITY DEFINER
  ```
- **Mathematical Specification**:
  - Distance: `sp.embedding <=> query_embedding` represents cosine distance $1 - \cos(\theta)$.
  - Similarity: `1 - (sp.embedding <=> query_embedding)`.
  - Filter: `sp.embedding IS NOT NULL AND 1 - (sp.embedding <=> query_embedding) >= match_threshold`.
  - Ordering: `ORDER BY sp.embedding <=> query_embedding ASC LIMIT match_count;`.
- **Key Edge Conditions**:
  - NULL embeddings in profiles must never match.
  - Exact match threshold boundary ($0.4000$ included, $0.3999$ excluded).
  - Empty database table returns empty list `[]`.
  - Zero/Antipodal vectors must not cause division by zero or NaN.

### 1.5 Strict Zero `public.*` Verification
- Zero reads, writes, joins, foreign keys, or references to:
  - `public.student_profiles`
  - `public.attendance_logs`
  - Any table or sequence under `public`.
- Verification mechanism:
  1. Static scan: Automated AST and regex parser traversing `scripts/` and `src/` to confirm absence of `public.` tokens in hostel code.
  2. Runtime verification: Inspecting all PostgREST URLs/queries generated by `src/utils/hostel_db.py` to ensure `.schema("girls_hostel")` is present and no calls leak to `public`.

---

## 2. Deep-Dive Analysis: Requirement R2 (Dual Camera Ingestion & Multi-Face Detection)

### 2.1 Dual Camera Ingestion Architecture
- **Camera Roles & Stream IDs**:
  - Entry Gate: `CAM_01_ENTRY`, role: `'ENTRY'`. Captures students returning to hostel.
  - Exit Gate: `CAM_02_EXIT`, role: `'EXIT'`. Captures students departing hostel.
- **Worker Concurrency**:
  - Ingestion workers run simultaneously on separate worker threads / processes (`CameraStreamWorker(camera_id, source, role)`).
  - Both streams ingest frames independently (nominal 15-30 FPS).
  - Thread safety: Independent frame buffers/queues; lock-free or mutex-guarded frame interchange; zero shared mutable state between streams.
  - Fault isolation: Camera 1 failure/disconnect must have zero impact on Camera 2.

### 2.2 Multi-Face Detection & ArcFace Feature Extraction
- **Model Pipeline**:
  - InsightFace (`FaceAnalysis(name='buffalo_l' or 'buffalo_sc')`) loaded with context `INSIGHTFACE_CTX_ID` (`-1` for CPU, `0` for GPU).
  - Detection Network: RetinaFace with Feature Pyramid Network (FPN) capable of detecting small to large faces across wide aspect ratios.
  - Recognition Network: ArcFace producing 512-dimensional continuous feature embeddings.
- **Concurrent Capacity**:
  - Detects up to 10 distinct student faces per frame batch concurrently.
  - Batch normalization: Every extracted embedding array $v$ is normalized via $v_{\text{norm}} = v / \|v\|_2$, guaranteeing $\|v_{\text{norm}}\|_2 = 1.0 \pm 1e-4$.

### 2.3 Latency SLA Validation (<200ms per Batch)
- **Measurement Protocol**:
  - High-precision timestamping: $t_{\text{start}} = \text{time.perf_counter()}$ immediately prior to batch inference; $t_{\text{end}} = \text{time.perf_counter()}$ immediately following vector extraction and normalization.
  - Latency SLA: $\Delta t = (t_{\text{end}} - t_{\text{start}}) \times 1000 < 200.0\text{ ms}$.
  - Test load: Synthetic frames with 1 face, 5 faces, and 10 concurrent faces.
  - Verification threshold: 95th percentile (P95) and average batch latency strictly below 200ms.

### 2.4 Backpressure & Stream Resilience
- Fixed-depth queue (size = 1 or 2 frames) to avoid queue lag. If processing takes 150ms and camera runs at 30 FPS (33ms/frame), older intermediate frames must be dropped to prevent queue starvation and latency accumulation.

---

## 3. Concrete Test Case Designs (Tier 1 & Tier 2)

### 3.1 Feature R1: Schema Isolation, RLS & Vector RPC

#### Tier 1: Feature Coverage (>=5 Tests)
| Test ID | Name | Objective | Input / Precondition | Execution Steps | Expected Outcome / Assertions |
|---------|------|-----------|----------------------|-----------------|-------------------------------|
| `R1-T1-01` | `test_r1_schema_and_tables_ddl_completeness` | Verify schema creation and complete DDL for all 4 hostel tables | `scripts/girls_hostel_schema.sql` | Parse SQL script via AST / DDL validator | 1. Schema `girls_hostel` created.<br>2. Tables `student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings` created.<br>3. Primary keys (UUID / BIGSERIAL) configured.<br>4. Foreign keys in `movement_logs` & `curfew_alerts` point to `girls_hostel.student_profiles(id)` with `ON DELETE CASCADE`. |
| `R1-T1-02` | `test_r1_row_level_security_enabled_on_all_tables` | Verify RLS enabled on all 4 tables in `girls_hostel` | `scripts/girls_hostel_schema.sql` | Inspect DDL statements for `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` | All 4 tables (`student_profiles`, `movement_logs`, `curfew_alerts`, `system_settings`) have RLS explicitly enabled; service_role grants present. |
| `R1-T1-03` | `test_r1_hnsw_vector_index_specification` | Verify HNSW vector index definition on embeddings | `scripts/girls_hostel_schema.sql` | Inspect index DDL for `idx_girls_hostel_students_embedding` | Index uses `USING hnsw` and operator class `(embedding vector_cosine_ops)` on `girls_hostel.student_profiles`. |
| `R1-T1-04` | `test_r1_match_face_rpc_signature_and_cosine_math` | Verify `match_face` RPC parameters, return types, and cosine similarity calculation | Schema DDL & Mock/Real DB fixture | Call `girls_hostel.match_face` with 512D query embedding matching an enrolled student ($s \approx 0.85$) and non-matching student ($s \approx 0.20$) | Returns matching student with similarity >= 0.40; excludes non-matching student; returns table schema `(id, name, roll_number, room_number, current_status, similarity)`. |
| `R1-T1-05` | `test_r1_strict_schema_isolation_zero_public_references` | Verify zero reads, writes, or references to `public.*` schema | Entire codebase under `src/` and `scripts/girls_hostel_schema.sql` | Scan files with regex `\bpublic\.(student_profiles\|attendance_logs)\b` and raw `public.` references | Zero matches found; `src/utils/hostel_db.py` routes all queries strictly through `.schema("girls_hostel")`. |
| `R1-T1-06` | `test_r1_hostel_db_client_crud_isolation` | Verify hostel database utility functions execute strictly within `girls_hostel` | `src/utils/hostel_db.py` & Mock/Real DB fixture | Execute `fetch_all_hostel_students()`, `update_student_movement_state()`, `fetch_recent_movement_logs()`, `fetch_overdue_curfew_students()` | All queries succeed; records inserted into `girls_hostel`; zero interaction with `public` tables. |

#### Tier 2: Boundary & Corner Cases (>=5 Tests)
| Test ID | Name | Objective | Input / Precondition | Execution Steps | Expected Outcome / Assertions |
|---------|------|-----------|----------------------|-----------------|-------------------------------|
| `R1-T2-01` | `test_r1_match_face_exact_threshold_boundary` | Test vector match filtering at exact 0.40 threshold boundary | Profiles with similarities $0.3999$, $0.4000$, and $0.4001$ relative to query vector | Call `match_face(query_embedding, match_threshold=0.40)` | Candidate at $0.3999$ is excluded; candidates at $0.4000$ and $0.4001$ are included in result. |
| `R1-T2-02` | `test_r1_match_face_extreme_geometric_vectors` | Test cosine calculation on orthogonal ($0.0$), identical ($1.0$), and antipodal ($-1.0$) vectors | Synthetic unit vectors with angles $0^\circ$, $90^\circ$, $180^\circ$ | Call `match_face` with identical, orthogonal, and antipodal query embeddings | Similarity for identical $= 1.0000 \pm 1e-4$; orthogonal $= 0.0000$; antipodal $= -1.0000$; no zero-division or NaN errors. |
| `R1-T2-03` | `test_r1_match_face_null_embedding_and_empty_db` | Verify graceful handling when database is empty or embeddings are NULL | Database with 0 students, and student with `embedding = NULL` | Call `match_face` with valid 512D query vector | Returns empty list `[]`; does not throw SQL exception; NULL embeddings strictly ignored. |
| `R1-T2-04` | `test_r1_match_face_match_count_boundary` | Test top-k limit boundaries (`match_count = 0, 1, 5`) | 4 profiles in DB exceeding threshold with similarities 0.90, 0.85, 0.70, 0.60 | Call `match_face` with `match_count=1`, `match_count=2`, `match_count=5` | `match_count=1` returns top match (0.90); `match_count=2` returns top 2 matches (0.90, 0.85); `match_count=5` returns all 4 matches without error. |
| `R1-T2-05` | `test_r1_malformed_query_embedding_rejection` | Test validation when query vector has wrong dimension, empty list, or NaN | Vectors of length 128, 513, empty `[]`, and `[NaN, ...]` | Pass invalid vectors into `match_face_embedding()` / `match_hostel_face()` | Raises `ValueError` or database client error cleanly without unhandled crash or database corruption. |
| `R1-T2-06` | `test_r1_foreign_key_cascade_deletion_isolation` | Verify cascading deletion of movement logs and curfew alerts on student profile deletion | Student profile with 3 movement logs and 2 curfew alerts | Delete student profile from `girls_hostel.student_profiles` | Foreign key `ON DELETE CASCADE` removes all associated records in `movement_logs` and `curfew_alerts`; zero orphan records remain. |

---

### 3.2 Feature R2: Dual Camera Ingestion & Multi-Face Detection

#### Tier 1: Feature Coverage (>=5 Tests)
| Test ID | Name | Objective | Input / Precondition | Execution Steps | Expected Outcome / Assertions |
|---------|------|-----------|----------------------|-----------------|-------------------------------|
| `R2-T1-01` | `test_r2_simultaneous_dual_camera_concurrency` | Verify concurrent, non-blocking ingestion on Camera 1 and Camera 2 | Mock dual video streams (`CAM_01_ENTRY`, `CAM_02_EXIT`) | Start both `CameraStreamWorker` instances concurrently; run for 3 seconds | Both workers active concurrently (`is_alive() == True`); both frame counters increment in parallel; no thread deadlock. |
| `R2-T1-02` | `test_r2_multi_face_detection_up_to_10_faces` | Verify simultaneous detection of up to 10 distinct faces in a single frame | Frame containing 10 distinct synthetic/test faces | Feed frame to face detection worker / `FaceAnalysis` | Exactly 10 faces detected; each has valid bounding box `[x1, y1, x2, y2]`, confidence score $\ge 0.5$, and 512D embedding. |
| `R2-T1-03` | `test_r2_frame_batch_latency_sla_under_200ms` | Benchmark batch processing latency for 10 concurrent faces | Frame with 10 faces; high-precision timer `time.perf_counter()` | Measure latency over 10 consecutive batches of 10 faces | Average batch latency $< 200.0$ ms; P95 batch latency $< 200.0$ ms. |
| `R2-T1-04` | `test_r2_512d_arcface_embedding_normalization` | Verify that all extracted facial embeddings are 512D and L2-normalized | Frame with multiple faces | Extract embeddings from detected faces; compute $\|v\|_2$ | Length of vector is exactly 512; Euclidean norm equals $1.0 \pm 1e-4$; data type is float32/float64. |
| `R2-T1-05` | `test_r2_camera_worker_independent_lifecycle` | Verify independent start, stop, and failure isolation between camera workers | Both camera stream workers running | Signal Camera 1 to stop; observe Camera 2; then signal Camera 2 to stop | Camera 1 stops within 2.0s; Camera 2 continues processing without interruption; Camera 2 stops cleanly upon request. |
| `R2-T1-06` | `test_r2_camera_queue_backpressure_and_frame_dropping` | Verify real-time queue management prevents frame latency lag | Fast camera input stream (60 FPS) with throttled batch processing | Feed frames rapidly into worker queue | Bounded queue (size $\le 2$) drops stale frames; worker always processes latest frame; frame latency does not drift above 200ms. |

#### Tier 2: Boundary & Corner Cases (>=5 Tests)
| Test ID | Name | Objective | Input / Precondition | Execution Steps | Expected Outcome / Assertions |
|---------|------|-----------|----------------------|-----------------|-------------------------------|
| `R2-T2-01` | `test_r2_empty_frame_zero_faces_boundary` | Test detector on empty frame (no humans present in hallway/gate) | Solid background frame (e.g. gray/texture) with 0 faces | Run detector on frame | Returns empty detection list `[]`; latency $< 20$ ms; zero exceptions or memory leaks. |
| `R2-T2-02` | `test_r2_face_capacity_overflow_boundary` | Test detector when face count exceeds nominal 10-face capacity (e.g. 12-15 faces) | Frame with 15 synthetic faces in gate crowd | Run detector on overloaded frame | System handles overflow gracefully (processes all 15 faces or bounds to top-10 by confidence); does not crash or exhaust RAM. |
| `R2-T2-03` | `test_r2_extreme_face_scales_tiny_and_massive` | Test detector on extreme face sizes ($20 \times 20$ px vs $600 \times 600$ px) | Frame with tiny face ($20 \times 20$ px) and large close-up face ($600 \times 600$ px) | Run detector on composite scale frame | Detects faces within valid scale envelope; bounding box coordinates strictly clamped within image boundaries $(0 \le x \le W, 0 \le y \le H)$. |
| `R2-T2-04` | `test_r2_extreme_pose_and_partial_occlusion` | Test detection with extreme head angles (yaw $> 45^\circ$, pitch $> 30^\circ$) | Faces with extreme profile yaw and downward pitch | Run detector and pose evaluator | Face detector locates face; pose estimation reports yaw/pitch accurately; embedding extraction succeeds. |
| `R2-T2-05` | `test_r2_corrupted_blank_and_malformed_frames` | Verify worker error handling on corrupted, zero-byte, or None frames | Injected `None` frames, $0$-byte buffers, and non-image numpy arrays | Feed malformed inputs to camera ingestion loop | Worker logs warning, discards invalid frame, and continues streaming without thread termination. |
| `R2-T2-06` | `test_r2_simulated_stream_disconnect_and_reconnection` | Test camera disconnect detection and automatic reconnection recovery | Mock stream that simulates RTSP connection drop after 5 frames, then resumes | Run camera worker through disconnect event | Worker flags stream lost, initiates reconnection with exponential backoff, and automatically resumes ingestion when stream recovers. |

---

## 4. Test Fixtures and Mock Boundaries Recommendation

### 4.1 Guiding Testing Principles
1. **Opaque-Box Integrity**: Never mock the unit/subsystem under test. Test real state machines, real SQL DDL syntax, real vector math, real concurrency, and real latency SLAs.
2. **External Boundary Isolation**: Only mock external physical hardware and external remote cloud services that are unavailable or non-deterministic in headless Linux CI environments:
   - Physical RTSP / USB cameras $\rightarrow$ Synthetic OpenCV video generator yielding deterministic frame sequences.
   - Remote Supabase Cloud $\rightarrow$ In-memory Schema-Isolated Supabase Mock that enforces schema isolation, table DDL, RLS, and vector cosine distance calculations.

### 4.2 Recommended Fixture Architecture

```
tests/
├── conftest.py                             # Pytest global fixtures & configuration
├── e2e/
│   ├── test_tier1_r1_schema_isolation.py   # R1 Tier 1 (DDL, RLS, RPC, Zero Public)
│   ├── test_tier1_r2_dual_camera.py        # R2 Tier 1 (Concurrency, 10 faces, <200ms latency)
│   ├── test_tier2_r1_boundary_cases.py     # R1 Tier 2 (Cosine thresholds, geometry, cascades)
│   ├── test_tier2_r2_boundary_cases.py     # R2 Tier 2 (Empty frames, crowd overflow, noise)
│   └── ...
└── fixtures/
    ├── mock_hostel_db.py                   # Schema-Isolated Supabase Mock Client
    ├── mock_camera_stream.py               # Synthetic Dual Video Stream Generator
    └── face_embedding_generator.py         # Deterministic 512D ArcFace Vector Generator
```

### 4.3 Detailed Specification of Fixtures

#### 1. `mock_hostel_db.py` (Schema-Isolated Supabase Mock)
- **Schema Isolation Guard**:
  - Internal storage: `self.storage = {"girls_hostel": {"student_profiles": {}, "movement_logs": {}, "curfew_alerts": {}, "system_settings": {}}}`.
  - Access validation: Any query attempting to access table without `.schema("girls_hostel")` or requesting `public.*` raises `SchemaIsolationViolationError("Access to public schema forbidden!")`.
- **Vector RPC Simulation (`girls_hostel.match_face`)**:
  - Implements vector cosine distance:
    $$\text{similarity}(u, v) = \frac{u \cdot v}{\|u\|_2 \|v\|_2} = 1 - (u \Leftrightarrow v)$$
  - Filters candidates where $\text{similarity} \ge \text{match\_threshold}$.
  - Sorts descending by similarity (ascending by cosine distance) and applies `LIMIT match_count`.
- **RLS Simulation**:
  - Verifies whether request context holds `service_role` key vs `anon` key. Denies unauthorized modifications under anon context.

#### 2. `mock_camera_stream.py` (Synthetic Dual Video Stream)
- Emulates `cv2.VideoCapture` API:
  - `read() -> Tuple[bool, np.ndarray]`
  - `isOpened() -> bool`
  - `release() -> None`
- Generates synthetic 720p/1080p BGR frames with configurable face counts ($0, 1, 2, \dots, 10, 15$).
- Can simulate FPS pacing (e.g. 30 FPS delay), frame drops, and stream disconnects.

#### 3. `face_embedding_generator.py` (Deterministic 512D Vectors)
- Generates unit-norm vectors:
  $$v \in \mathbb{R}^{512}, \quad \|v\|_2 = 1.0$$
- Allows generating pairs of vectors with precisely calibrated cosine similarities:
  $$v_2 = s \cdot v_1 + \sqrt{1 - s^2} \cdot v_\perp$$
  enabling exact boundary testing for thresholds like $0.3999$ vs $0.4000$ vs $0.4001$.

---

## 5. Verification Commands
To execute the R1 and R2 E2E test suites independently:
```bash
# Run Tier 1 R1 & R2 tests
pytest tests/e2e/test_tier1_r1_schema_isolation.py tests/e2e/test_tier1_r2_dual_camera.py -v

# Run Tier 2 R1 & R2 boundary tests
pytest tests/e2e/test_tier2_r1_boundary_cases.py tests/e2e/test_tier2_r2_boundary_cases.py -v

# Run entire R1 & R2 test suite with latency benchmark logging
pytest tests/e2e/test_tier1_r1* tests/e2e/test_tier1_r2* tests/e2e/test_tier2_r1* tests/e2e/test_tier2_r2* -v -s
```
