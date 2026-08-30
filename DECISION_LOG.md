# Decision Log

## 1. Key assumptions

| Assumption | Why | Risk if wrong |
|---|---|---|
| **`Tentative Close Date` is the forecast field** | `Close Date (A)` is 92% null (318/344); it cannot support forecasting | Forecast windows shift |
| **Fiscal year starts in April** | Indian company; configurable via `FISCAL_YEAR_START_MONTH` | "This quarter" means Jan–Mar instead |
| **Dates are day-first (DD/MM)** | Indian convention; genuinely ambiguous values are flagged in the ledger, not hidden | Some dates off by months |
| **Win rate = won / (won + lost), by deal count** | Open deals in the denominator would make the rate fall as the pipeline grows. Counted by number, not value, because 52% of values are missing | A value-weighted rate would differ |
| **Probability weights High 0.75 / Medium 0.45 / Low 0.20** | Standard sales convention; 75% of deals are blank, so weight is inferred from funnel stage and **flagged as inferred** | Weighted pipeline shifts proportionally |
| **`Project Completed` sits with the won stages** | It has no letter prefix, breaking the A.–O. convention | Funnel ordering would be wrong |
| **Deal Status is authoritative for won/lost, not stage** | The lettered stages don't line up with outcome — `I. POC` sorts after `G. Project Won` | Misclassified outcomes |

## 2. Architecture: deterministic engine, LLM front-end

Four options were considered: LLM + tools + deterministic analytics (A); a multi-step agentic loop (B); text-to-SQL over a semantic layer (C); and Monday's MCP with the model reading rows directly (D).

**Chose A.** The organising invariant is that **the LLM never produces a number**. It does two things — turn a question into a typed plan, and write prose around figures it is handed. Metric values reach the UI directly from the analytics engine, bypassing the model entirely.

- **B** rejected: the question space here is genuinely enumerable, so a multi-step loop buys flexibility we don't need while adding latency and failure modes to a live demo.
- **C** rejected *for now*: right at 10× the data, but with source data this messy you end up writing normalization in SQL — the worst place for it — and the LLM-generated join is exactly where silent wrong answers come from.
- **D** rejected: MCP hands raw board JSON to the model and lets it do arithmetic. Fastest to build, and it fails the core requirement.

**Consequence:** every LLM failure degrades to worse *wording*, never a wrong *number*.

## 3. Technology choices

| Choice | Reasoning |
|---|---|
| **Python + FastAPI + pandas** | The heaviest work is data normalization; Python's tooling there is unmatched |
| **No agent framework** | The system makes one structured call. LangChain/LangGraph would add ~20 transitive dependencies and an abstraction layer over a single tool call. Rejecting it is the engineering decision |
| **Not DuckDB — yet** | At 520 rows, pandas is simpler and normalization belongs in Python. First thing I'd add at scale |
| **Provider-abstracted LLM** (Groq / Anthropic / Ollama) | Free hosted tier for the demo, a paid fallback if rate limited, local Ollama for offline development. One env var, no code change |
| **Vanilla JS frontend served by FastAPI** | *Deviation from plan — see §8* |

## 4. Monday.com: GraphQL API over MCP

| | GraphQL API | MCP |
|---|---|---|
| Control over pagination/retry | Full | Limited |
| Read-only enforcement | Trivial — no mutation code exists | Depends on exposed tools |
| Fits a deterministic pipeline | Natively | Inverted — MCP wants the *model* driving |

MCP's core value is letting a model explore a workspace. Here the model must never see raw rows, so that value becomes a liability.

**Robustness decisions:** boards resolved by **name**, not hardcoded ID (re-importing changes the ID, rarely the name); columns mapped through an **alias table**, so renaming "Masked Deal value" to "Deal Value" doesn't break the app; missing columns degrade the answer rather than crashing it.

## 5. Data findings that shaped the build

**The customer join is impossible — and this is the most important finding.**
Deals masks customers as `COMPANY089`; Work Orders masks them as `WOCOMPANY_002`. **Zero overlap.** Any fuzzy match between them would fabricate a relationship that does not exist. The agent refuses this question explicitly and explains why.

**What does join:**
- **Deal name** — 52 of 58 work-order accounts match (89.7%). But it is *not unique* on the Deals board (`Sakura` appears 27 times), so it's an **account alias, not a deal key**. Both sides are aggregated before joining; a naive row-level merge would inflate every total. There's a test for this.
- **Sector** — 6 shared values after normalization.
- **Owner code** — 6 shared `OWNER_xxx` codes.

**Other findings:** two rows contain their own headers as data (dropped, counted); 61% of won deals have no value; four Work Order columns are 100% empty, so **no AR/collections metrics were built**; `Billing Status` contains the typo `BIlled`.

## 6. Normalization strategy

**Never destroy information.** Every field keeps its `_raw` twin beside the normalized value, and every transformation is counted into the ledger.

**Missing amounts become `None`, never `0`.** With 52% of values blank, zero-filling would silently corrupt every total and average. This is the single highest-consequence rule in the codebase and it has its own test.

Unrecognised statuses and sectors are **preserved and reported**, never dropped — an unmapped value is a data finding, not a bad row. Rows lacking a planned end date are excluded from the delay metric rather than assumed on-time.

*A bug worth recording:* the currency regex `\brs\.?\b` matched only `Rs` in `Rs. 1,00,000`, leaving a stray dot that parsed as `0.1`. Caught by a unit test before it reached anything.

## 7. Agent design

The **enum-constrained plan schema is the anti-hallucination mechanism** — the model cannot invent an intent, metric, board or sector. Unknown values are rejected at the boundary and fall back to keyword routing.

**Assume and state, don't interrogate.** "How is the pipeline?" is answered with a stated assumption, not a clarifying question. Clarification is reserved for cases where readings differ materially (e.g. "how did we do?" — sales or delivery?).

**Number verification:** after generation, every numeral in the prose is checked against the computed results. A mismatch discards the narration and renders from a deterministic template.

**Fallbacks:** a keyword planner and a template narrator mean the demo survives an LLM outage with identical figures and plainer prose.

## 8. Trade-offs

**Frontend: vanilla JS served by FastAPI instead of Next.js on Vercel.** *This is a deliberate deviation from my own plan.* With 5 hours rather than 6, two deployments was the largest schedule risk, and the plan itself identified "a live URL" as the highest-value must-have. Serving one artifact removes the second deploy, the CORS surface, and the build step. Cost: no React component ecosystem, and charts are hand-rolled CSS rather than Recharts. Worth it.

**`DATA_SOURCE=local_csv`** is a development-only source, off by default, that reads the cleaned CSVs through the *same* normalization pipeline. It is not a mock of the Monday API and never fabricates records; every response it produces carries a visible warning. It exists so the stack could be built while boards were importing, and as demo insurance.

**Other trade-offs:** pandas over SQL (simplicity now, DuckDB later); single-pass over multi-step (reliability over flexibility); 5-minute cache (staleness vs rate limits, with stale-serving on failure); test depth concentrated on normalization and metrics, where bugs actually live.

## 9. Known limitations

- **No customer-level cross-board analysis** — the data cannot support it (§5)
- **No receivables or collections analysis** — four source columns are entirely empty
- **Won revenue is understated** — 61% of won deals carry no value; the agent says so every time
- **Actual close-date trends are unavailable** — 92% null
- No persistence, no auth, no multi-user; conversation memory is the last 2 turns
- Free-tier hosting cold-starts after idle (~30–50s); warm the URL before demoing
- Fiscal quarter assumption is configurable but unverified against Skylark's actual calendar

## 10. What I'd do with more time

*(The golden-question eval suite was on this list and has since been built — 92 tests pinning metric values for 16 founder questions, running in CI. It immediately found two real defects in the ledger's own accounting, which is the argument for it.)*


1. **DuckDB semantic layer** — a metric definition compiles to SQL, so adding metrics stops meaning adding Python.
3. **Ask Skylark for a customer-code mapping table** — it would unlock the entire customer-level cross-board dimension that is currently impossible.
4. Webhook-driven incremental sync instead of TTL polling.
5. Scheduled leadership briefing delivered to Slack.
6. Per-user auth with Monday OAuth, so board visibility follows the user's own permissions.
