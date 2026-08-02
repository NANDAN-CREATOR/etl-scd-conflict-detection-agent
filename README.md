# Day 13 — ETL SCD Type Conflict Detection Agent

**Series:** Agentic AI in Data Engineering — ETL Edition  
**Domain:** Data Modelling  
**Pattern:** Pre-load guardrail — validate that the SCD strategy applied to incoming dimension records matches the registered SCD contract for each column.  
**Core guardrail:** Never allow a Type 1 (overwrite) merge to silently clobber a column that is registered as Type 2 (history-tracked). Destroying versioned history is irreversible.

---

## The Problem

Dimension tables in a data warehouse are loaded using **Slowly Changing Dimension (SCD)** strategies:

- **Type 1** — just overwrite the old value; no history kept
- **Type 2** — create a new versioned row; full history preserved
- **Type 3** — keep only current and previous value in the same row

Each column in a dimension table has a registered SCD type that reflects a business decision. The problem: pipelines get refactored, engineers add columns, merge scripts get copy-pasted — and a column that was supposed to be Type 2 quietly gets loaded with a Type 1 overwrite. No error. No warning. The history simply disappears.

---

## What the Agent Does

Before any dimension load begins, the agent:

1. **Fetches the SCD contract** for the target dimension table
2. **Detects SCD type conflicts** — compares each proposed column operation against the registered type
3. **Checks nullable constraints** — validates that NOT NULL columns are not being loaded with nulls
4. **Approves, blocks, or escalates** based on severity

---

## Core Guardrail

> A Type 1 overwrite on a Type 2 registered column is a **CRITICAL** violation and always results in a block — regardless of how routine the incoming record looks.

Secondary guardrail: if no SCD contract exists for a dimension, the agent must **escalate** — never approve a dimension load without a verifiable contract.

---

## Scenarios

| # | Dimension | Situation | Outcome |
|---|-----------|-----------|---------|
| 1 | `dim_customer` | All columns match registered SCD types | ✅ APPROVED |
| 2 | `dim_customer` | `credit_tier` + `customer_segment` loaded as Type 1 (should be Type 2) | 🚫 BLOCKED — TYPE1_OVERWRITE_ON_TYPE2_COLUMN |
| 3 | `dim_product` | New column `loyalty_score` not in SCD contract | 🚫 BLOCKED — UNKNOWN_COLUMNS_NOT_IN_CONTRACT |
| 4 | `dim_vendor` | No SCD contract registered at all | ⚠️ ESCALATED — NO_SCD_CONTRACT |

---

## Project Structure

```
etl-scd-conflict-detection-agent/
├── agent.py          # Core agent: SCD contracts, tools, agentic loop, 4 scenarios
├── requirements.txt  # No external deps (stdlib only)
├── .gitignore
├── LICENSE
└── README.md
```

---

## How to Run

```bash
pip install -r requirements.txt   # nothing to install
python agent.py
```

---

## New Agentic Pattern vs Prior Days

| Day | Stage | Pattern |
|-----|-------|---------|
| 10 | Load | Row-count reconciliation after load |
| 11 | Extract | Schema drift detection |
| 12 | Extract | Partition filter verification before extract |
| **13** | **Data Modelling** | **SCD type contract enforcement before dimension load** |

Day 12 asks: *"Will this extract scan the right partitions?"*  
Day 13 asks: *"Will this load apply the right historical versioning strategy to each column?"*

---

## License

MIT
