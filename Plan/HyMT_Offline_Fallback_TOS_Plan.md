# Hy-MT Offline Fallback + Translation Operating System Plan

## Objective

Implement Hy-MT as an offline fallback for cloud LLM quota/network failures, while preparing a gradual migration path where Hy-MT becomes the primary rewrite engine after the system has accumulated enough project-specific knowledge from cloud LLM, rule engine, and validator feedback.

## Current Role Split

Early stage:

```text
Cloud LLM = primary translator/refiner
Hy-MT offline = fallback when cloud providers fail/quota/rate-limit
Rule/Validator = hard safety gate
```

Later stage:

```text
Knowledge Graph + Rule Engine = source of truth
Hy-MT offline = primary rewrite/MT engine
Cloud LLM = teacher/auditor/entity enrichment when available
```

## Non-Negotiable Design Rules

- Do not let Hy-MT own terminology decisions.
- Do not require Hy-MT to return complex JSON.
- Preserve segment count/order/id exactly.
- Never write final output if validator fails.
- Offline fallback must preserve current stage artifact layout:
  - `Output/<novel>/Intermediate/<chapter>/pre-trans/stage1_entity_review.json`
  - `Output/<novel>/Intermediate/<chapter>/pre-trans/stage2_context_pack.json`
  - `Output/<novel>/Intermediate/<chapter>/pre-trans/stage3_ai_refiner.json`
  - `Output/<novel>/State/*`
  - `Output/<novel>/Final_Translated/*`

## Phase 1 - Local Hy-MT Runtime

### Files

```text
bin/hymt_server.sh
bin/hymt_keepalive.sh
models/hymt/README.md
logs/hymt_server.log
```

### Requirements

- `hymt_server.sh` starts llama.cpp OpenAI-compatible server on `127.0.0.1:8088`.
- Default model path: `models/hymt/Hy-MT1.5-1.8B-2bit.gguf`.
- Allow override:
  - `HYMT_MODEL`
  - `HYMT_HOST`
  - `HYMT_PORT`
  - `HYMT_THREADS`
  - `HYMT_CTX`
- `hymt_keepalive.sh` keeps server alive and logs restarts.
- Scripts must work on `/sdcard` noexec by running through `bash script`.

### Acceptance

- If `llama-server` missing, script exits with clear message.
- If model missing, script exits with clear message.
- If server starts, `/v1/chat/completions` works with local provider config.

## Phase 2 - AI Provider Policy

### Files

```text
Script/ai_client.py
ai_providers.json
Test/test_hymt_fallback.py
```

### Requirements

- Preserve existing provider fallback behavior.
- Add provider metadata support:
  - `role`: `primary`, `offline_fallback`, `offline_primary`
  - `local`: bool
- Local provider should not require real API key. Use `api_key=local` if missing.
- Improve provider result metadata so callers can know which provider was used.
- Keep public API backward compatible:
  - `call_ai_checked(...) -> (text, err)` still works.
- Add optional API:
  - `call_ai_checked_with_meta(...) -> (text, err, meta)`

### Fallback Policy

```text
cloud primary providers by priority
→ rate-limit/quota/network fail
→ local_hymt provider
→ CLI fallback only if enabled
```

### Acceptance

- Simulated HTTP 429 on cloud provider calls local Hy-MT provider next.
- Local provider can be called with empty/missing key.
- Provider used is recorded in meta/log.

## Phase 3 - Offline Stage3 Adapter

### Files

```text
Script/stage3_ai_refiner.py
Script/stage3_offline_hymt.py (optional if cleaner)
Test/test_hymt_fallback.py
```

### Requirements

- If cloud provider succeeds, current JSON Stage3 path remains primary.
- If cloud fails and local Hy-MT returns text, normalize into Stage3 schema.
- Do not ask Hy-MT for full schema.
- For fallback, process each segment or small batch with strict IDs.
- Output schema remains:

```json
{
  "refined_segments": [{"id": 1, "refined_translation": "..."}],
  "story_timeline": {"summary": {"main_events": "", "new_characters": []}},
  "new_entities": [],
  "relationships": [],
  "provider_meta": {"provider": "local_hymt", "mode": "offline_fallback"}
}
```

### Acceptance

- Segment IDs/order preserved.
- Fallback output passes `PipelineManager._validate_stage3`.
- If Hy-MT returns too few/many lines, stage fails cleanly and chapter stays pending/error.

## Phase 4 - Validator Hardening For Offline Output

### Files

```text
Script/qc_checker.py
Test/test_hymt_fallback.py
```

### Requirements

- Entity lock check still applies.
- Segment count check still applies.
- Empty/too-short output fails.
- Chinese residue threshold warns or fails based on severity.
- No final write if QC fails.

### Acceptance

- Bad fallback output does not write `Final_Translated`.
- TOC status remains recoverable.

## Phase 5 - Knowledge Graph Preparation

### Files

```text
Script/knowledge_graph.py
Script/rule_translation_engine.py
Script/term_discovery.py
```

### SQLite Schema

```sql
CREATE TABLE IF NOT EXISTS entities(
  id INTEGER PRIMARY KEY,
  novel_id TEXT,
  cn TEXT,
  vi TEXT,
  type TEXT,
  aliases TEXT,
  gender TEXT,
  first_chapter INTEGER,
  confidence REAL DEFAULT 0,
  status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS glossary(
  id INTEGER PRIMARY KEY,
  novel_id TEXT,
  cn TEXT,
  vi TEXT,
  category TEXT,
  priority INTEGER DEFAULT 100,
  status TEXT DEFAULT 'pending'
);

CREATE TABLE IF NOT EXISTS realms(
  id INTEGER PRIMARY KEY,
  novel_id TEXT,
  cn TEXT,
  vi TEXT,
  level INTEGER,
  system TEXT
);

CREATE TABLE IF NOT EXISTS relations(
  source_id INTEGER,
  target_id INTEGER,
  relation_type TEXT,
  confidence REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pending_terms(
  id INTEGER PRIMARY KEY,
  novel_id TEXT,
  cn TEXT,
  type_guess TEXT,
  freq INTEGER DEFAULT 1,
  first_seen INTEGER,
  last_seen INTEGER,
  samples TEXT
);

CREATE TABLE IF NOT EXISTS translation_memory(
  cn_hash TEXT PRIMARY KEY,
  novel_id TEXT,
  cn_text TEXT,
  vi_text TEXT,
  provider TEXT,
  quality_score REAL,
  created_at TEXT
);
```

### Acceptance

- Module can init DB per novel.
- Stage1/init seed can write candidate entities later.
- Does not change current pipeline behavior until explicitly enabled.

## Phase 6 - Test On 5 Real Chapters

### Test Novel

Use current real split source:

```text
Source_Split/Rạp Chiếu Phim Địa Ngục
```

### Test Method

- Do not destroy current translated finals.
- Prefer temp output:

```text
/tmp/hymt-5chap-output/Rạp Chiếu Phim Địa Ngục
```

- Copy/use first 5 real chapter files.
- Monkeypatch/fake cloud quota in tests where needed.
- If real Hy-MT server unavailable, run provider-fallback unit tests and stage normalization smoke with fake local provider response.

### Acceptance

- 5 real chapters reach at least Stage3 fallback smoke path.
- Stage artifacts written under per-chapter `pre-trans` folders.
- Final output written only for passing chapters.
- Test report includes provider used and failures.

## Execution Delegation Rule

Coding implementation should be performed by AGY. Main agent role:

- write/maintain this plan
- launch AGY with explicit scope
- review AGY diff
- run tests
- correct direction if AGY drifts
- restart services only after tests pass

## AGY Implementation Prompt

Implement Phases 1-4 first. Keep changes scoped. Do not implement the full graph migration unless Phases 1-4 are green.

Concrete deliverables:

1. `bin/hymt_server.sh`
2. `bin/hymt_keepalive.sh`
3. local provider support and metadata in `Script/ai_client.py`
4. offline fallback adapter in Stage3 path
5. tests covering cloud quota → local fallback, segment preservation, and artifact layout
6. smoke helper/test for first 5 real chapters with fake local provider if real server is absent

Do not break existing cloud provider behavior. Do not change final output layout.
