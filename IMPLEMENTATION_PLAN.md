# Skylark Drones — Monday.com BI Agent
## Detailed Implementation Plan (Phase 2)

> Grounded in actual inspection of `Deal funnel Data.xlsx` (346 rows x 12 cols) and
> `Work_Order_Tracker Data.xlsx` (176 rows x 38 cols, header on row 2).

---

## 0. What the Data Actually Told Us

Seven findings that changed the plan. These are the things most candidates will miss.

### 0.1 There is a real cross-board join key — and it is NOT the customer

| Candidate key | Deals | Work Orders | Verdict |
|---|---|---|---|
| **Deal Name** | `Deal Name` (155 uniq / 346 rows) | `Deal name masked` (58 uniq / 176 rows) | **52 of 58 overlap (89.7%)** — this is the join |
| Customer code | `COMPANY089` | `WOCOMPANY_002` | **Different masking namespaces. Zero overlap. Cannot be joined.** |
| Owner code | `OWNER_001..007` | `OWNER_001..006, 008` | 6 shared — usable for owner-level cross-board |
| Sector | 12 values | 6 values | Joins cleanly after normalization |

**This is the single highest-value finding.** Any submission that fuzzy-matches customers
across these two boards is fabricating a relationship that does not exist. We will state
this explicitly, and it becomes a Decision Log highlight.

Nuance to handle honestly: `Deal Name` is **not unique** in the Deals board (`Sakura`
appears 27 times, `Alphonse` 19). It behaves as an **account/programme alias**, not a deal
primary key. So the join is **many-to-many at the account level**, not a deal-to-WO foreign
key. We aggregate both sides before joining to avoid row-multiplication inflation.

### 0.2 Repeated header rows are embedded inside the data
Two rows in Deals contain the literal strings `"Deal Stage"`, `"Deal Status"`,
`"Sector/service"`, `"Created Date"` as *values*. The sheets were concatenated with headers
intact. Naive loading silently creates a phantom sector called "Sector/service".
Fix: explicit header-echo detection in the normalizer, reported in the ledger.

### 0.3 52% of deal values are missing — and it is worst where it matters most

| Deal Status | Rows | With a value | Missing |
|---|---|---|---|
| Won | 165 | 64 | **101 (61%)** |
| Dead | 127 | 54 | 73 (57%) |
| Open | 49 | 47 | 2 (4%) |
| On Hold | 2 | 0 | 2 (100%) |

Open pipeline is nearly complete; **won revenue is 61% unknown**. This is the headline
data-quality story of the entire assignment and drives the demo.

### 0.4 Dates are strings, not dates
Every date column in Deals is `object` dtype — `Created Date`, `Tentative Close Date`,
`Close Date (A)` all arrive as text and must be parsed. `Close Date (A)` is **92% null**
(318/346), so *actual* close dates are unusable for most analysis; `Tentative Close Date`
(79% populated) is the workable forecast field. WO dates are properly typed already.

### 0.5 Deal Stage is an ordered funnel — with a broken entry
Stages are lettered `A. Lead Generated` through `O. Not Relevant at all`, giving a free
funnel ordering and probability ladder. But **`Project Completed` (19 rows) has no letter
prefix** — it breaks the convention and sorts wrongly unless explicitly mapped.

### 0.6 Work Order status vocabulary is messy in specific, fixable ways
- `Execution Status`: 7 values incl. `Executed until current month`, `Pause / struck`, `Details pending from Client`
- `Billing Status`: contains the typo **`BIlled`** alongside `Partially Billed`
- `Actual Billing Month`: mixes **`Dec`** with full month names
- **4 columns are 100% empty**: `Expected Billing Month`, `Actual Collection Month`, `Collection status`, `Collection Date`
  → We must **not** build collection/AR metrics. The data cannot support them.

### 0.7 Amounts are clean floats — so the messiness is *missingness*, not formatting
Both boards store amounts as numeric. There are no `$100,000` / `100K` / `Rs 1,00,000`
strings in the source. **However**, Monday.com import will coerce many of these to text.
So we still build the full currency parser (it earns its place post-import), but we
**stop claiming** the source data has mixed currency formats. Accuracy over theatre.

---

## 1. Architecture (unchanged and now validated)

Deterministic analytics engine with an LLM front-end. The LLM **plans** and **narrates**;
it never sees raw rows and never produces a number.

```
Question
  -> LLM Planner (enum-constrained tool schema) -> QueryPlan
  -> Executor -> Monday GraphQL (cached, paginated)
  -> Normalizer -> canonical DataFrames + Quality Ledger
  -> Analytics engine (pandas) -> MetricResult[] with provenance
  -> LLM Narrator (data fenced as untrusted) -> prose
  -> Response: prose + verbatim metrics + ledger + follow-ups
```

Metric values travel to the UI **directly from the analytics engine**, bypassing the model.
A hallucinating narrator can only produce worse wording, never a wrong number.

### Stack
| Layer | Choice |
|---|---|
| Backend | Python 3.11 + FastAPI + pandas |
| LLM | Provider-abstracted: `groq` (free, fast) / `anthropic` / `ollama` (local dev) |
| Monday | Direct GraphQL API, read-only |
| Frontend | Next.js 14 + TypeScript + Tailwind + shadcn/ui + Recharts |
| Deploy | Render (API) + Vercel (UI) |
| Tests | pytest |

---

## 2. Monday.com Board Configuration

### 2.1 Pre-import cleaning (`scripts/prepare_for_monday.py`)
Do **not** hand-clean in Excel — a script is reproducible and is itself evidence of rigor.

1. Read Deals with default header; read WO with `header=1`.
2. Drop rows where `Deal Stage == "Deal Stage"` (header echoes).
3. Drop the 4 fully-empty WO columns.
4. Trim whitespace on all string columns.
5. Emit `deals_clean.csv` / `work_orders_clean.csv`.
6. **Preserve all other messiness** — the agent must handle it live, not receive it pre-solved.

### 2.2 Deals board columns

| Source column | Monday type | Reason |
|---|---|---|
| Deal Name | **Text** (item name) | Not unique — deliberately not a key column |
| Owner code | **Status** | 7 values, low cardinality, filterable |
| Client Code | **Text** | 199 values — too many for a dropdown |
| Deal Status | **Status** | 4 real values; drives open/won/lost |
| Deal Stage | **Status** | 17 values; ordered funnel |
| Sector/service | **Dropdown** | 12 values; primary grouping dimension |
| Masked Deal value | **Numbers** | Preserves null vs 0 distinction (critical) |
| Closure Probability | **Status** | High/Medium/Low, drives weighting |
| Tentative Close Date | **Date** | Primary forecast field (79% populated) |
| Close Date (A) | **Date** | 92% null — retained, rarely usable |
| Created Date | **Date** | Pipeline aging |
| Product deal | **Dropdown** | 10 values |

### 2.3 Work Orders board columns (18 of 34 retained)

| Source column | Monday type | Reason |
|---|---|---|
| Deal name masked | **Text** (item name) | **The cross-board join key** |
| Serial # | **Text** | Unique WO id (176/176 unique) |
| Customer Name Code | **Text** | Note: not joinable to Deals |
| Sector | **Dropdown** | Joins to Deals sector |
| Execution Status | **Status** | Drives active/complete/delayed |
| Nature of Work | **Dropdown** | One-time / Monthly / ARC / PoC |
| Type of Work | **Text** | 36 values — too many for dropdown |
| BD/KAM Personnel code | **Status** | Owner join |
| Probable Start / End Date | **Date** | Duration + delay detection |
| Data Delivery Date | **Date** | Actual delivery |
| Date of PO/LOI | **Date** | Order intake |
| Amount (Excl GST) | **Numbers** | Primary WO value |
| Amount (Incl GST) | **Numbers** | |
| Billed Value (Excl GST) | **Numbers** | Billing progress |
| Amount Receivable | **Numbers** | AR exposure |
| Invoice Status | **Status** | |
| WO Status (billed) | **Status** | Open/Closed |
| Document Type | **Dropdown** | |

**Dropped:** the 4 empty columns, plus quantity and month-name columns that add no
analytical value at this scope. Documented in the Decision Log.

---

## 3. Canonical Schema

```python
class Deal:
    deal_name_raw, deal_name_norm          # join key, normalized lowercase
    owner_code, client_code
    status_raw, status_norm                # Won | Lost | Open | OnHold | Unknown
    stage_raw, stage_norm, stage_order     # int 1-15; "Project Completed" mapped explicitly
    sector_raw, sector_norm
    amount_raw, amount_value: float | None # NEVER zero-filled
    probability_raw, probability_weight    # High=0.75 Medium=0.45 Low=0.2 None=stage default
    tentative_close_date, actual_close_date, created_date  # date | None
    is_open, is_won, is_lost               # derived booleans
    age_days: int | None
    quality_flags: list[str]

class WorkOrder:
    wo_id (Serial #), deal_name_raw, deal_name_norm
    customer_code, sector_raw, sector_norm, owner_code
    exec_status_raw, exec_status_norm      # NotStarted|InProgress|Completed|Paused|Blocked
    nature_of_work, type_of_work
    start_date, end_date, delivery_date, po_date
    amount_excl_gst, amount_incl_gst, billed_value, receivable
    is_active, is_complete, is_delayed, delay_days, duration_days
    quality_flags: list[str]
```

**Invariant:** every normalized field keeps its `_raw` twin. The pipeline never destroys
information; it only adds interpretation.

---

## 4. Normalization Rules (exact)

### Header-echo detection
Drop any row where a categorical field equals its own column name. Log count.

### Status
```
won                                      -> Won
dead, lost, project lost                 -> Lost
open                                     -> Open
on hold, projects on hold, pause/struck  -> OnHold
<unmapped>                               -> Unknown  (preserved + counted, never dropped)
```

### Stage (ordered)
`A. Lead Generated`=1 ... `O. Not Relevant at all`=15, parsed from the letter prefix.
**`Project Completed` is explicitly mapped to order 8** (post-Won), since it has no prefix.
Unmapped -> order `None`, flagged `stage_unordered`.

### Execution Status (WO)
```
completed, executed until current month  -> Completed
ongoing                                  -> InProgress
not started                              -> NotStarted
pause / struck                           -> Paused
partial completed                        -> PartiallyComplete
details pending from client              -> Blocked
```

### Sector
Lowercase -> strip -> collapse whitespace -> alias table. Reject the `Sector/service`
header echo. Deals has 12 sectors, WO has 6 — the 6 shared are the cross-board universe.

### Dates
Try ISO -> `dateutil(dayfirst=True)` -> explicit patterns. Unparseable -> `None` +
`date_unparseable`. Post-Monday-import, expect text dates; the parser handles both.

### Amounts
Strip currency symbols and separators; handle lakh grouping (`1,00,000`); expand
`K`/`L`/`Cr`/`M`. Unparseable or blank -> **`None`, never `0`**. Flag `amount_missing`.

### Derived
```
is_delayed  = end_date < today AND exec_status != Completed
delay_days  = (today - end_date).days
duration    = delivery_date - start_date        # completed only
age_days    = today - created_date              # open deals only
```

---

## 5. Analytics Engine

Each metric is a registered function returning:
```python
MetricResult(value, unit, label, formula, definition,
             rows_included, rows_excluded, exclusion_reasons: dict)
```

### Deal metrics
- `total_open_pipeline` — sum of amount where `is_open`. *(47 of 49 open deals have values — high confidence)*
- `weighted_pipeline` — sum of amount x probability_weight
- `won_revenue` — sum of amount where `is_won`. **Reports 61% missingness prominently**
- `lost_value`, `win_rate` = won / (won + lost), closed only; `None` if denominator 0
- `avg_deal_size`, `median_deal_size` — median leads (distribution is heavily skewed)
- `pipeline_by_sector` / `_by_owner` / `_by_stage`
- `funnel_distribution` — uses `stage_order`
- `pipeline_aging` — open deals by `age_days` bucket
- `stale_deals` — `tentative_close_date` in the past AND still open
- `deals_closing_this_quarter`

### Work Order metrics
- `total_wo`, `active_wo`, `completed_wo`, `delayed_wo`
- `completion_rate` = Completed / total
- `avg_project_duration` — completed only
- `wo_by_sector` / `_by_customer` / `_by_status` / `_by_nature`
- `overdue_backlog` — count + value of delayed WOs
- `billing_gap` = sum(amount_excl_gst - billed_value) where positive
- `unbilled_completed` — Completed but `Invoice Status = "Not billed yet"` (high-signal risk metric)

### Cross-board metrics
- `sector_opportunity_matrix` — pipeline (x) vs completion-rate (y) across the 6 shared sectors
- `deal_to_execution_link` — account-level join on `deal_name_norm`; **both sides pre-aggregated** to avoid many-to-many inflation
- `accounts_with_pipeline_and_delivery_risk` — open pipeline + delayed WOs on the same account
- `won_vs_delivered_by_sector`
- `owner_sales_vs_delivery` — via shared OWNER codes
- `unlinked_coverage` — 6 of 58 WO accounts have no matching deal; always reported

### Explicitly NOT built (data cannot support)
Collection/AR ageing (4 empty columns) · customer-level cross-board joins (namespace
mismatch) · actual-close-date trends (92% null) · quarter-over-quarter on won revenue
(61% missing values makes it misleading).

---

## 6. Data Quality Ledger

Every response carries:
```json
{ "rows_considered": 346, "rows_included": 47, "rows_excluded": 299,
  "exclusions": { "not_open": 297, "amount_missing": 2 },
  "normalizations": { "dates_parsed": 344, "header_echo_rows_dropped": 2,
                      "status_unmapped": 0 },
  "confidence": "high",
  "notes": ["Open-deal amounts are 96% complete."] }
```

**Confidence is per-query**, weighted only by fields that query touched:
`>90%` High · `70-90%` Medium · `<70%` Low.
So `total_open_pipeline` is High, `won_revenue` is **Low (61% missing)**. This
field-scoped scoring is what makes the feature credible rather than decorative.

---

## 7. Agent Layer

### Planner tool schema
```
build_query_plan(
  intent: enum[pipeline, weighted_pipeline, won_revenue, win_rate,
               deal_risk, sector_breakdown, owner_performance, funnel,
               work_order_status, delivery_performance, delayed_work,
               billing_risk, cross_board_sector, cross_board_account,
               executive_summary, data_quality, leadership_update],
  boards: list[deals | work_orders],
  filters: { sector, owner, status[], stage[], nature_of_work,
             date_field, date_range{preset|start|end} },
  metrics: list[str],            # validated against the registry
  group_by: enum[sector|owner|stage|status|account|month]|null,
  assumptions: list[str],
  confidence_in_interpretation: enum[high|medium|low]
)
```
Enum constraints are the anti-hallucination mechanism — the model cannot invent an intent
or metric. Unknown metric produces a clean "I don't compute that yet, here's what I do."

### Clarify policy
Clarify only when readings differ **materially in number**. Otherwise assume, state the
assumption, offer alternatives as follow-up chips.

### Narrator contract
Receives only aggregates + ledger, never rows. Board-derived text is fenced in
`<untrusted_data>`. Post-generation, every numeral in the prose is verified against the
result object; mismatch falls back to a deterministic template.

---

## 8. Frontend

Single page. Header (`Skylark Business Intelligence` + freshness chips + read-only badge)
-> conversation -> structured response card:

**Answer** -> **Key Metrics** (2-4 cards, definition on hover) -> **Insight** ->
**Risks & Caveats** (amber) -> **Data Quality** (collapsed, expandable) -> **Follow-ups**.

Charts only where earned: sector bar, funnel (uses `stage_order`), 2x2 sector matrix.
Plan chips render before the answer streams, so interpretation is visible and correctable.

---

## 9. Repository

```
skylark-monday-bi-agent/
├── README.md · DECISION_LOG.md · .env.example · .gitignore · docker-compose.yml
├── backend/app/
│   ├── main.py · config.py
│   ├── api/{chat,health}.py
│   ├── monday/{client,queries,board_resolver,cache}.py    # QUERIES ONLY
│   ├── data/{schema,normalizers,pipeline,quality,matching}.py
│   ├── analytics/{registry,deals,work_orders,cross_board,executive}.py
│   ├── agent/{planner,executor,narrator,fallback,prompts}.py
│   ├── llm/{base,groq,anthropic,ollama}.py                # provider abstraction
│   └── models/
├── backend/tests/{test_normalizers,test_metrics,test_monday_client,test_planner}.py
├── frontend/  (Next.js App Router)
└── scripts/{prepare_for_monday,inspect_boards}.py
```

---

## 10. Security

Secrets server-side only; frontend talks only to our API. **Read-only enforced
structurally** — no mutation string exists in the codebase, asserted by a test.
Prompt injection is answered by architecture: the Planner never sees board data, so the
main attack surface does not exist. The Narrator sees fenced aggregates only, and numbers
bypass it entirely. Board text is scanned for instruction-shaped strings and surfaced as a
data-quality warning — a security control reframed as a feature.

---

## 11. Error Handling

| Failure | Response |
|---|---|
| Monday 5xx | 3 retries -> stale cache with staleness warning -> clear error |
| 429 / complexity | Honor `Retry-After`, smaller page, retry |
| 401 | Distinct config error, never retried |
| Empty board / missing column | Degrade and say what's unavailable |
| All rows invalid for a metric | **Refuse the number** — never return 0 |
| LLM planner down | Keyword fallback planner (top 8 intents) |
| LLM narrator down | Template rendering; numbers still correct |

**Invariant: no failure path produces a number that isn't real.**

---

## 12. Testing

**Unit (~30)** — header-echo drop · date parsing incl. unparseable · amount parsing
(`1,00,000`, `2.5Cr`, empty) · status/stage/sector alias maps incl. unmapped ·
`Project Completed` maps to order 8 · every metric on a fixture with known answers ·
**`win_rate` with 0 closed deals returns `None`, not ZeroDivisionError** ·
missing amounts excluded not zeroed · median vs mean on skewed data.

**Integration (~6)** — paginated fetch (mocked) · 401 · empty board · missing column ·
429 retry · cache hit/miss.

**Agent (~10)** — assert *plan shape*, not prose.

**Guardrail** — injected board text doesn't alter behavior · every prose numeral exists in
the result object · no `mutation` anywhere in the codebase.

---

## 13. Six-Hour Execution Plan

| Time | Work | Exit criterion |
|---|---|---|
| **0:00-0:25** | `prepare_for_monday.py`; create both boards, import, set column types per §2 | Boards live and typed |
| **0:25-1:00** | Repo scaffold, config, LLM provider abstraction, Monday client (auth, board resolution, pagination), `inspect_boards.py` | Both boards fetching end-to-end |
| **1:00-2:00** | Normalizers + canonical schema + ledger. **Tests written inline** | Raw JSON -> clean frames + ledger, tests green |
| **2:00-3:00** | Analytics: registry, deals, work orders, cross-board. Metric tests | All metrics computing with provenance |
| **3:00-4:00** | Planner + tool schema + prompts, executor, narrator + number verification, fallbacks | `curl` a real question, correct answer |
| **4:00-5:00** | Frontend: chat, response card, metric cards, quality panel, plan chips, sector matrix | Full UX local |
| **5:00-5:30** | Deploy both; smoke-test all 9 demo questions **on the live URL** | Public URL answering |
| **5:30-6:00** | README, Decision Log, edge cases, rehearsal | Submission-ready |

Deploy at 5:00, not 5:45 — deployment always surprises you.

### Scope discipline
**Must:** integration · normalization · ~12 metrics · plan-to-answer loop · missing-data
reporting · chat UI · error handling · live URL · README + Decision Log.
**Should (the marks):** ledger · per-query confidence · plan chips · sector matrix ·
account-level cross-board · fallbacks · unit tests · number verification.
**Nice:** leadership briefing · funnel chart · follow-ups · injection warnings.
**Cut first:** leadership briefing, then charts beyond the matrix.

---

## 14. Demo Script

1. **"What's our total pipeline?"** — the ledger lands in the first 20 seconds
2. **"How's our pipeline looking for the energy sector this quarter?"** — the assignment's own example. *(Note: there is no "Energy" sector — the real ones are Renewables/Mining/Powerline/Railways. The agent should say so and suggest the closest match. **This is a strong moment** — it refuses to invent a sector.)*
3. **"Which sectors have the strongest pipeline?"** — grouping + chart
4. **"How many work orders are delayed?"** — board two, status normalization, derived field
5. **"Which sectors have strong pipeline but weak execution?"** — the 2x2 matrix (centerpiece)
6. **"Which accounts have both open pipeline and delivery risk?"** — account-level join, with coverage stated
7. **"What's our won revenue?"** — answers, then flags **61% of won deals have no value**. The honesty moment.
8. **"What data quality problems do we have?"** — turns messy data into a capability
9. **"How's the business?"** — assume-and-state rather than stalling

Opening line: *"Most BI chatbots will confidently give you a wrong number. This one tells
you which rows it couldn't use, and why."*

---

## 15. Decision Log Contents

1. **Assumptions** — `Tentative Close Date` as the forecast field · probability weights
   0.75/0.45/0.2 · win rate = closed deals only · calendar quarters · `Project Completed`
   mapped to order 8
2. **Architecture** — options table; the "LLM never produces a number" invariant
3. **Technology** — Python for pandas · **no agent framework, and why** · not DuckDB *yet* ·
   Groq for free hosted inference · Ollama for offline dev
4. **Monday integration** — GraphQL over MCP with reasons · board resolution by name ·
   column alias mapping
5. **Data findings** — **customer codes are not joinable across boards; Deal Name is the
   only viable link at 90% coverage, and it is account-level not deal-level** · header
   echoes · 61% won-value missingness · 4 empty columns
6. **Normalization** — raw preserved · nulls excluded not imputed · **why missing amounts
   are never zeroed**
7. **Agent design** — enum-constrained schema as the anti-hallucination mechanism ·
   assume-and-state · fallback paths
8. **Leadership update** — interpreted as composition of existing metrics; scoped Should-Have
9. **Trade-offs** — pandas vs SQL · single-pass vs multi-step agent · cache staleness ·
   test depth vs feature breadth
10. **Limitations** — no AR/collection analysis · no customer-level cross-board · Render
    cold starts · no persistence · last-2-turn context
11. **With more time** — DuckDB semantic layer · eval suite over golden questions ·
    webhook sync · Slack briefing delivery · request a customer-code mapping table from
    Skylark to unlock true customer-level analysis

---

## 16. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Monday import coerces dates/numbers to text | **High** | Normalizer already handles both; set column types explicitly at import |
| Many-to-many `Deal Name` join inflates totals | **High** | Pre-aggregate both sides before joining; assert row counts in tests |
| Evaluator asks about "Energy" (doesn't exist) | **High** | Agent names the real sectors and suggests closest — a feature, not a failure |
| Render cold start during evaluation | High | Uptime ping + README note + warm before demo |
| Scope creep | High | Cut line pre-decided (§13) |
| Groq rate limits mid-demo | Low | Anthropic key configured as fallback provider |
| 61% missing won-values makes revenue answers look weak | Medium | Reframe as the ledger's showcase — transparency is the product |

---

## 17. Why This Stands Out

1. **The LLM structurally cannot produce a wrong number** — not careful prompting, architecture.
2. **The data-quality ledger turns the assignment's deliberate messiness into the best part of the demo.**
3. **We found the real join and proved the obvious one is impossible.** Most candidates will
   fuzzy-match customer codes and silently fabricate a relationship.
4. **Honest refusal** — "all matching deals have missing amounts" instead of returning 0.
5. **Documented rejections** — no LangChain, no MCP, no AR metrics. Restraint reads as seniority.
6. **Graceful degradation everywhere** — the demo survives an API outage.
7. **Prompt injection answered structurally**, not with a filter.

**Positioning:** *Most submissions will build a chatbot that reads Monday.com. This builds a
BI system that happens to have a conversational interface — and it tells you when it doesn't know.*
