# Demo Script

**https://skylark-monday-bi-agent-tply.onrender.com**

> **Load the URL 5 minutes before demoing.** Free-tier hosting sleeps after ~15 minutes idle and takes 30–50s to wake. After that, responses are 2–5s.
>
> **Leave ~15 seconds between questions.** Groq's free tier limits tokens per minute. If you rush it you'll get an amber "language model unavailable" note — correct numbers, plainer prose. That's the fallback working, but it's not what you want on camera.

---

## Opening line

> "Most BI chatbots will confidently give you a wrong number. This one tells you which records it couldn't use, and why."

Point at the header: `Deals · 344 items · 0s ago` and `Work Orders · 176 items · 0s ago`. Live Monday data, read-only.

---

## 1. "What's our total pipeline?"

**What to point out, in this order:**

- The **plan chips** appear above the answer — `pipeline` · `deals`. The agent shows its interpretation *before* the number, so a misread is catchable.
- **Metric cards** — hover one. Definition plus the exact formula: `sum of deal value where Deal Status = Open`. Under it: `47/49 records`.
- Click the collapsed **`high confidence · 47 of 49 records used`** row. It expands to exclusions and cleaning steps, including *"repeated header rows removed: 2"* — two rows in the source contained their own column headers as data, detected and dropped at query time.

**Say:** "Every number carries its own audit trail. Nothing is silently dropped."

---

## 2. "How's our pipeline looking for the energy sector this quarter?"

The assignment's own example question. **There is no Energy sector in this data.**

Watch for the amber **"Assumed:"** box — *"Interpreted 'energy' as 'Renewables', and Powerline may also be relevant."*

**Say:** "It doesn't invent a sector, and it doesn't refuse. It picks a defensible reading and shows its work so you can correct it."

---

## 3. "Which sectors have the strongest pipeline but weak execution?"

The cross-board showpiece. Plan chips now show **both boards**.

Scroll to the **2×2 scatter** — pipeline on x, delivery completion on y, bubbles sized by work-order count, the "Fix delivery" quadrant shaded red.

**The finding: Railways carries ₹5.20 Cr of pipeline at a 15% completion rate, with 11 of 13 work orders delayed. Mining runs at 84%.**

**Say:** "This view only exists because both boards are present. We're selling into a sector we're currently failing to deliver in."

---

## 4. "Which accounts have both open pipeline and delivery risk?"

**Sakura: ₹39.72 Cr open pipeline, 4 delayed work orders.**

Note the caveat: *"Customer codes cannot be matched across boards — Deals uses `COMPANY###`, Work Orders uses `WOCOMPANY_###`, with no overlap."*

**Say:** "The obvious join — customer — is impossible; the two boards mask customers in different namespaces with zero overlap. So we join on deal/account name instead, which covers 53 of 59 accounts, and we report that coverage rather than hiding the unmatched tail. Fuzzy-matching those customer codes would have fabricated a relationship that doesn't exist."

*This is the strongest technical moment in the demo.*

---

## 5. "What's our won revenue?"

**₹9.50 Cr — and the confidence chip turns red: `low confidence`.**

Leading risk: *"101 of 165 won deals (61%) have no value recorded, so true won revenue is higher than this figure."*

**Say:** "Compare that to question one on the same board — high confidence there, low here. Confidence is scored on the fields each question actually touches, not a global badge. Open pipeline is 96% complete; won revenue is 39%."

---

## 6. "What data quality problems do we have?"

A first-class answer, not an error page. 52% of deals missing value, 21.5% missing close dates, 35.8% of work orders missing billed value, plus the two structural findings.

**Say:** "The messy data was deliberate. Being able to describe it precisely is a capability, not an apology."

---

## 7. "What changed this quarter?"

**New pipeline created fell 93.8% — ₹35.40 Cr in Q3 FY26 down to ₹2.20 Cr in Q4 FY26.**

Note the caveat: *"No deals were created in Q2 FY27, so this compares the two most recent quarters that contain records."*

**Say:** "The data stops in Q4 FY26, so a literal 'this quarter vs last quarter' would compare nothing against nothing. It walks back to the most recent quarters that have records and tells you it did. Movement is measured by creation date, because that's the only date field complete enough to support a comparison — close dates are 92% empty."

---

## 8. "Prepare this week's leadership update."

The optional requirement, interpreted as a briefing built for decisions.

- **Talking points** with a **Copy** button — paste straight into a deck
- **Risks ranked by materiality**, each carrying its own figure
- Quarter-on-quarter movement, sector matrix, accounts at risk

**Say:** "Every risk line has a number attached. A risk without a figure is an opinion, and there's a test that enforces it."

---

## If asked "how do you stop it hallucinating?"

Three layers, in order of strength:

1. **The LLM never produces a number.** It writes a query plan and it writes prose. Metric values travel from the analytics engine straight to the screen, bypassing the model entirely.
2. **Every numeral in the generated prose is verified** against the computed results. A mismatch discards the narration and renders from a template. *This fired in production during testing — the model tried to state a figure we never computed, and the system threw the whole answer away.*
3. **Computed caveats outrank generated ones.** The engine said open deals were *past* their close date; the model paraphrased it as *missing*. Different finding, different fix — so computed statements now lead and paraphrases follow.

## If asked about prompt injection

The planner never sees board data. A malicious deal name can't reach the component that decides what to do — the attack surface doesn't exist. The narrator sees only aggregates, fenced as untrusted, and can't affect numbers. Board text is also screened for instruction-shaped content and surfaced as a data-quality warning.

## If asked "why no LangChain?"

One structured tool call. A framework would add ~20 transitive dependencies and an abstraction layer over a single call. The system is ~2,500 lines of readable Python instead.

## If asked what you'd do next

An eval suite over a golden question set in CI; a DuckDB semantic layer so adding a metric stops meaning adding Python; and asking Skylark for a customer-code mapping table, which would unlock the entire customer-level cross-board dimension that's currently impossible.

---

## Backup plans

| If | Then |
|---|---|
| Site is slow to load | It's a cold start — wait 45s, it only happens once |
| Amber "model unavailable" note | Groq rate limit. Numbers are still correct. Say "that's the fallback — the figures are computed in Python, so an LLM outage costs us prose, not accuracy." Wait 30s and retry |
| Monday API is down | The agent serves cached data with an explicit staleness warning |
| Everything is down | `git clone`, set `DATA_SOURCE=local_csv`, `uvicorn app.main:app` — runs offline against the same pipeline |
