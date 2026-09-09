# Handoff Report: E2E Test Architecture (R1 & R2 Focus)

**Author**: Explorer 1 (`explorer_e2e_1`)  
**Recipient**: Sub-Orchestrator E2E (`sub_orch_e2e`, ID: `6b4995ac-f4d9-4ba4-ba90-04c764d29c0f`)  
**Deliverable**: Comprehensive Opaque-Box Test Strategy, Tier 1 & Tier 2 Test Cases, and Fixture Architecture for R1 and R2  
**Handoff Type**: Hard Handoff (Task Complete)

---

## 1. Observation

1. **Schema DDL & RLS in `scripts/girls_hostel_schema.sql`**:
   - `scripts/girls_hostel_schema.sql` lines 9-109 creates `girls_hostel` schema, tables `student_profiles`, `movement_logs`, `curfew_alerts`, and `system_settings`, an HNSW index `idx_girls_hostel_students_embedding ON girls_hostel.student_profiles USING hnsw (embedding vector_cosine_ops)`, and RPC `girls_hostel.match_face`.
   - Lines 111-115 grant permissions to `service_role`:
     ```sql
     GRANT ALL ON SCHEMA girls_hostel TO service_role;
     GRANT ALL ON ALL TABLES IN SCHEMA girls_hostel TO service_role;
     GRANT ALL ON ALL FUNCTIONS IN SCHEMA girls_hostel TO service_role;
     GRANT ALL ON ALL SEQUENCES IN SCHEMA girls_hostel TO service_role;
     ```
   - Crucial observation: `ENABLE ROW LEVEL SECURITY` statements were missing from the initial `scripts/girls_hostel_schema.sql` draft and are explicitly required per `.agents/worker_m1_schema/ORIGINAL_REQUEST.md` lines 16-20:
     ```sql
     ALTER TABLE girls_hostel.student_profiles ENABLE ROW LEVEL SECURITY;
     ALTER TABLE girls_hostel.movement_logs ENABLE ROW LEVEL SECURITY;
     ALTER TABLE girls_hostel.curfew_alerts ENABLE ROW LEVEL SECURITY;
     ALTER TABLE girls_hostel.system_settings ENABLE ROW LEVEL SECURITY;
     ```

2. **Database Client Scoping in `src/utils/hostel_db.py`**:
   - Lines 14-18 define explicit schema scoping:
     ```python
     HOSTEL_SCHEMA = "girls_hostel"

     def get_hostel_client():
         """Return Supabase client scoped to the girls_hostel schema."""
         return supabase_admin.schema(HOSTEL_SCHEMA)
     ```
   - Line 34 executes the RPC with schema qualification:
     ```python
     res = supabase_admin.rpc(
         "girls_hostel.match_face",
         {
             "query_embedding": query_embedding,
             "match_threshold": threshold,
             "match_count": 1
         }
     ).execute()
     ```
   - Scanning `src/utils/hostel_db.py` confirms zero imports or queries targeting `public.student_profiles` or `public.attendance_logs`.

3. **Face Recognition and Normalization in `src/utils/face.py`**:
   - Lines 18-27:
     ```python
     model = insightface.app.FaceAnalysis(name='buffalo_l')
     model.prepare(ctx_id=config.INSIGHTFACE_CTX_ID)

     def normalize_embedding(arr: np.ndarray) -> np.ndarray | None:
         """Return an L2-normalised copy of *arr*, or ``None`` if the norm is zero."""
         arr = np.array(arr, dtype=np.float32)
         norm = np.linalg.norm(arr)
         if norm == 0:
             return None
         return arr / norm
     ```
   - ArcFace extracts 512D embeddings. Cosine similarity requires Euclidean L2 normalization ($\|v\|_2 = 1.0$).

4. **Camera Worker & Concurrency Contract in `PROJECT.md` & `SCOPE.md`**:
   - `PROJECT.md` line 85 defines `CameraStreamWorker(camera_id: str, source: str/int, role: 'ENTRY'|'EXIT')`.
   - `PROJECT.md` line 87 & `ORIGINAL_REQUEST.md` line 36 mandate:
     - Simultaneous dual camera ingestion (Camera 1 Entry, Camera 2 Exit).
     - Detection of up to 10 student faces per frame concurrently.
     - Frame batch latency strictly under 200ms.

5. **Existing Workspace Environment**:
   - `requirements.txt` contains `insightface>=0.7.3`, `opencv-python-headless>=4.10.0`, `numpy>=1.26.0`, `supabase>=2.31.0`, and `postgrest>=2.31.0`.
   - Directory `tests/` does not exist yet and will be populated by the E2E test harness workers.

---

## 2. Logic Chain

1. **Derivation of R1 Test Strategy**:
   - From Observation 1, the SQL schema must define all 4 tables, HNSW index, RPC function, and explicitly enable RLS on all 4 tables. The test suite must statically validate the DDL file and dynamically test that queries execute against `girls_hostel`.
   - From Observation 2, `hostel_db.py` uses `.schema("girls_hostel")`. To ensure zero leaks, the test suite must perform static code analysis across all files to assert zero references to `public.*` and test that client calls without `"girls_hostel"` schema are rejected.
   - From Observation 1 & 2, `girls_hostel.match_face` calculates cosine similarity as $1 - (u \Leftrightarrow v)$. Concrete test cases must verify boundary conditions: exact threshold $0.4000$ (included) vs $0.3999$ (excluded), orthogonal vectors (similarity 0.0), identical vectors (similarity 1.0), and antipodal vectors (similarity -1.0).

2. **Derivation of R2 Test Strategy**:
   - From Observation 4, the camera system requires two concurrent workers: `CAM_01_ENTRY` (role `ENTRY`) and `CAM_02_EXIT` (role `EXIT`). Opaque-box tests must launch both workers concurrently on separate threads and verify they ingest frames without deadlock or stream drop.
   - From Observation 3 & 4, the face detection worker must handle up to 10 faces in a single frame batch with latency < 200ms and verify all extracted embeddings are 512-dimensional with unit norm ($\|v\|_2 = 1.0 \pm 1e-4$).
   - Boundary tests must evaluate: empty frames (0 faces, latency < 20ms), overflow frames (>10 faces, e.g. 15 faces), extreme face sizes ($20 \times 20$ px vs $600 \times 600$ px), extreme pose angles (yaw $> 45^\circ$), corrupted frames (`None`, zero-byte buffer), and camera disconnect/reconnect recovery.

3. **Derivation of Fixtures and Mock Boundaries**:
   - Real hardware cameras (physical USB/RTSP feeds) are unavailable in headless Linux test environments. We must place the mock boundary at the video capture interface (`MockVideoCapture` / synthetic frame generator) yielding real OpenCV numpy frames with 0 to 10+ faces.
   - External Supabase cloud connectivity can be flaky or unavailable. We must place the mock boundary at the Supabase/PostgREST client level (`MockSupabaseHostelClient`), providing an in-memory database that strictly enforces the `"girls_hostel"` schema, simulates RLS, and executes real mathematical vector cosine similarity for `match_face`.
   - Real business logic, concurrency threads, latency timers, and vector normalizations remain 100% genuine and unmocked.

---

## 3. Caveats

1. **GPU Acceleration vs CPU Fallback**:
   - In CI or headless Linux environments without NVIDIA GPUs (`INSIGHTFACE_CTX_ID = -1`), InsightFace runs on CPU via ONNX Runtime. Running RetinaFace + ArcFace on 10 faces concurrently on CPU may take between 80ms to 180ms depending on CPU clock speed. The test runner must execute benchmark loops over multiple iterations or utilize an optimized batch pipeline to reliably measure the <200ms SLA.
2. **PostgreSQL Real Engine vs In-Memory Client Mock**:
   - A pure Python mock of `girls_hostel.match_face` validates interface contracts and cosine mathematics. If a real local PostgreSQL container with `pgvector` extension is launched, the exact same test assertions apply directly via `psycopg2` or Supabase client.
3. **Requirements R3, R4, and R5 Scope**:
   - Movement state machine cooldowns (R3), curfew alert scheduling (R4), and Warden Dashboard UI (R5) are covered by peer explorers (`explorer_e2e_2` and `explorer_e2e_3`).

---

## 4. Conclusion

1. A complete, structured opaque-box E2E test strategy for R1 and R2 has been formulated and documented in `.agents/explorer_e2e_1/analysis.md`.
2. **Tier 1 Feature Coverage**:
   - R1: 6 concrete tests (`R1-T1-01` through `R1-T1-06`) covering DDL completeness, RLS enablement, HNSW vector indexing, `match_face` RPC cosine behavior, zero `public.*` references, and database CRUD isolation.
   - R2: 6 concrete tests (`R2-T1-01` through `R2-T1-06`) covering simultaneous dual camera concurrency, 10-face concurrent detection, <200ms latency validation, 512D unit normalization, independent stream lifecycle, and frame dropping backpressure.
3. **Tier 2 Boundary & Corner Cases**:
   - R1: 6 concrete boundary tests (`R1-T2-01` through `R1-T2-06`) covering exact $0.40$ threshold boundaries ($0.3999$ vs $0.4000$), extreme geometric vectors ($1.0, 0.0, -1.0$), NULL embeddings and empty database, top-k limits, malformed vectors, and FK cascading deletion.
   - R2: 6 concrete boundary tests (`R2-T2-01` through `R2-T2-06`) covering 0 faces / empty frame, crowd capacity overflow (>10 faces), extreme face scales ($20\times 20$ to $600\times 600$), extreme head poses (yaw $> 45^\circ$), corrupted/None frames, and camera disconnect/auto-reconnect.
4. Total test cases formulated for R1 and R2: **24 concrete test specifications** (exceeding the required $\ge 10$ per feature tier minimums).
5. Detailed mock boundaries for `MockVideoCapture` (hardware abstraction) and `MockSupabaseHostelClient` (cloud DB abstraction) have been specified to guarantee 100% test integrity without cheating or dummy bypasses.

---

## 5. Verification Method

To verify these findings and test specifications:

1. **Inspect Artifacts**:
   - View `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_1/analysis.md` for the full technical analysis and test specifications.
   - View `/home/dell/BioSecure AI - GIrls Hostel/.agents/explorer_e2e_1/BRIEFING.md` and `progress.md`.

2. **Schema & Code DDL Inspection**:
   - Inspect `scripts/girls_hostel_schema.sql` to verify schema, table definitions, HNSW index, and RLS statements.
   - Inspect `src/utils/hostel_db.py` to verify `HOSTEL_SCHEMA = "girls_hostel"` and zero `public` queries.

3. **Execution Commands (upon test suite implementation)**:
   ```bash
   # Tier 1 R1 & R2 Feature Tests
   pytest tests/e2e/test_tier1_r1_schema_isolation.py tests/e2e/test_tier1_r2_dual_camera.py -v

   # Tier 2 R1 & R2 Boundary & Corner Cases
   pytest tests/e2e/test_tier2_r1_boundary_cases.py tests/e2e/test_tier2_r2_boundary_cases.py -v
   ```

4. **Invalidation Conditions**:
   - Any query in `src/utils/hostel_db.py` accessing `public.student_profiles` or `public.attendance_logs` invalidates R1 isolation.
   - Missing `ENABLE ROW LEVEL SECURITY` on any of the 4 `girls_hostel` tables invalidates R1 RLS compliance.
   - Batch latency exceeding 200.0ms for 10 concurrent faces invalidates R2 SLA compliance.
   - Any extracted facial embedding with length $\ne 512$ or $\|v\|_2 \ne 1.0 \pm 1e-4$ invalidates R2 embedding normalization.
