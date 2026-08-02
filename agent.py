"""
Day 13 — ETL SCD Type Conflict Detection Agent
===============================================
Domain   : Data Modelling (ETL)
Pattern  : Pre-load guardrail — validate that the SCD strategy applied to incoming
           dimension records matches the registered SCD contract for each column.
Guardrail: NEVER allow a Type 1 (overwrite) merge to silently clobber a column that
           is registered as Type 2 (history-tracked), even if the incoming change
           looks like a routine update. Destroying versioned history is irreversible.
"""

import datetime
from typing import Optional

SCD_CONTRACTS = {
    "dim_customer": {
        "natural_key": "customer_id",
        "columns": {
            "email":            {"scd_type": 1, "nullable": True},
            "phone":            {"scd_type": 1, "nullable": True},
            "marketing_opt_in": {"scd_type": 1, "nullable": False},
            "customer_segment": {"scd_type": 2, "nullable": False},
            "credit_tier":      {"scd_type": 2, "nullable": False},
            "home_country":     {"scd_type": 2, "nullable": False},
            "account_manager":  {"scd_type": 3, "nullable": True},
        },
        "registered_at": "2025-01-15",
    },
    "dim_product": {
        "natural_key": "product_sku",
        "columns": {
            "product_name":    {"scd_type": 1, "nullable": False},
            "unit_cost":       {"scd_type": 2, "nullable": False},
            "category":        {"scd_type": 2, "nullable": False},
            "supplier_id":     {"scd_type": 2, "nullable": True},
            "list_price":      {"scd_type": 3, "nullable": False},
            "is_discontinued": {"scd_type": 1, "nullable": False},
        },
        "registered_at": "2025-03-01",
    },
    "dim_employee": {
        "natural_key": "employee_id",
        "columns": {
            "preferred_name": {"scd_type": 1, "nullable": True},
            "work_email":     {"scd_type": 1, "nullable": False},
            "department":     {"scd_type": 2, "nullable": False},
            "job_title":      {"scd_type": 2, "nullable": False},
            "salary_band":    {"scd_type": 2, "nullable": False},
            "manager_id":     {"scd_type": 3, "nullable": True},
        },
        "registered_at": "2024-11-20",
    },
}


def get_scd_contract(dimension_name):
    if dimension_name not in SCD_CONTRACTS:
        return {"dimension": dimension_name, "status": "NO_CONTRACT",
                "message": f"No SCD contract registered for '{dimension_name}'. Cannot validate column-level SCD types before load."}
    contract = SCD_CONTRACTS[dimension_name].copy()
    contract["dimension"] = dimension_name
    contract["status"] = "OK"
    return contract


def detect_scd_conflicts(dimension_name, proposed_operations):
    contract = get_scd_contract(dimension_name)
    if contract["status"] == "NO_CONTRACT":
        return {"status": "UNVERIFIABLE", "dimension": dimension_name, "conflicts": [],
                "message": contract["message"]}
    registered_columns = contract["columns"]
    conflicts, unknowns, valid = [], [], []
    for op in proposed_operations:
        col = op["column"]
        applied = op["applied_scd_type"]
        if col not in registered_columns:
            unknowns.append({"column": col, "issue": "COLUMN_NOT_IN_CONTRACT",
                             "detail": f"Column '{col}' is not registered in the SCD contract for '{dimension_name}'."})
            continue
        expected = registered_columns[col]["scd_type"]
        if applied != expected:
            severity = "CRITICAL" if expected == 2 and applied == 1 else "WARNING"
            conflicts.append({"column": col, "expected_scd_type": expected,
                              "applied_scd_type": applied, "severity": severity,
                              "detail": (
                                  f"Column '{col}' is registered as Type {expected} but pipeline is applying Type {applied}. "
                                  + ("A Type 1 overwrite on a Type 2 column will permanently destroy versioned history — this is irreversible."
                                     if severity == "CRITICAL"
                                     else f"Type {applied} applied where Type {expected} is expected.")
                              )})
        else:
            valid.append(col)
    critical = [c for c in conflicts if c["severity"] == "CRITICAL"]
    warnings = [c for c in conflicts if c["severity"] == "WARNING"]
    return {"status": "CONFLICTS_FOUND" if conflicts or unknowns else "CLEAN",
            "dimension": dimension_name, "valid_columns": valid, "conflicts": conflicts,
            "unknown_columns": unknowns, "critical_count": len(critical),
            "warning_count": len(warnings), "unknown_count": len(unknowns)}


def check_nullable_violations(dimension_name, incoming_record):
    contract = get_scd_contract(dimension_name)
    if contract["status"] == "NO_CONTRACT":
        return {"status": "UNVERIFIABLE", "violations": []}
    violations = []
    for col, spec in contract["columns"].items():
        if not spec["nullable"] and col in incoming_record:
            val = incoming_record[col]
            if val is None or val == "":
                violations.append({"column": col, "detail": f"Column '{col}' is NOT NULL in contract but incoming value is null/empty."})
    return {"status": "VIOLATIONS_FOUND" if violations else "CLEAN",
            "dimension": dimension_name, "violations": violations, "violation_count": len(violations)}


def approve_dimension_load(dimension_name, summary):
    return {"action": "APPROVED", "dimension": dimension_name, "summary": summary,
            "message": "SCD contracts verified. Dimension load may proceed."}

def block_dimension_load(dimension_name, reason, detail):
    return {"action": "BLOCKED", "dimension": dimension_name, "reason": reason,
            "detail": detail, "message": "Dimension load blocked. Fix SCD type conflicts before proceeding."}

def escalate_to_human(dimension_name, reason, detail):
    return {"action": "ESCALATED", "dimension": dimension_name, "reason": reason,
            "detail": detail, "message": "SCD contract unavailable. Human review required before load."}


def run_agent(scenario):
    trace = []
    dimension = scenario["dimension"]
    proposed_ops = scenario.get("proposed_operations", [])
    incoming_record = scenario.get("incoming_record", {})

    contract = get_scd_contract(dimension)
    trace.append({"tool": "get_scd_contract", "result": contract})

    if contract["status"] == "NO_CONTRACT":
        trace.append({"tool": "escalate_to_human",
                      "result": escalate_to_human(dimension, "NO_SCD_CONTRACT", contract["message"])})
        return trace

    conflict_result = detect_scd_conflicts(dimension, proposed_ops)
    trace.append({"tool": "detect_scd_conflicts", "result": conflict_result})

    null_result = check_nullable_violations(dimension, incoming_record) if incoming_record else {"status": "CLEAN", "violations": [], "violation_count": 0}
    trace.append({"tool": "check_nullable_violations", "result": null_result})

    if conflict_result.get("critical_count", 0) > 0:
        critical_cols = [c["column"] for c in conflict_result["conflicts"] if c.get("severity") == "CRITICAL"]
        trace.append({"tool": "block_dimension_load", "result": block_dimension_load(
            dimension, "TYPE1_OVERWRITE_ON_TYPE2_COLUMN",
            f"Critical SCD conflict on column(s): {critical_cols}. A Type 1 overwrite on a Type 2 history-tracked column permanently destroys versioned lineage. This cannot be undone.")})
    elif conflict_result.get("unknown_count", 0) > 0:
        unknown_cols = [u["column"] for u in conflict_result.get("unknown_columns", [])]
        trace.append({"tool": "block_dimension_load", "result": block_dimension_load(
            dimension, "UNKNOWN_COLUMNS_NOT_IN_CONTRACT",
            f"Pipeline is operating on column(s) {unknown_cols} which are not in the registered SCD contract. Update the contract before loading.")})
    elif null_result.get("violation_count", 0) > 0:
        trace.append({"tool": "block_dimension_load", "result": block_dimension_load(
            dimension, "NULLABLE_CONSTRAINT_VIOLATION",
            f"{null_result['violation_count']} NOT NULL constraint(s) violated in incoming record.")})
    elif conflict_result.get("warning_count", 0) > 0:
        warn_cols = [c["column"] for c in conflict_result["conflicts"] if c.get("severity") == "WARNING"]
        trace.append({"tool": "block_dimension_load", "result": block_dimension_load(
            dimension, "SCD_TYPE_MISMATCH_WARNING",
            f"SCD type mismatch on column(s): {warn_cols}. Review contract alignment before proceeding.")})
    else:
        trace.append({"tool": "approve_dimension_load", "result": approve_dimension_load(
            dimension, f"All {len(conflict_result['valid_columns'])} column(s) match registered SCD types. No nullable violations.")})
    return trace


SCENARIOS = [
    {"id": 1, "name": "Clean load — all columns match registered SCD types",
     "description": "Pipeline correctly applies Type 1 to overwriteable columns and Type 2 to history-tracked columns for dim_customer. Should APPROVE.",
     "dimension": "dim_customer",
     "proposed_operations": [{"column": "email", "applied_scd_type": 1}, {"column": "phone", "applied_scd_type": 1}, {"column": "customer_segment", "applied_scd_type": 2}, {"column": "credit_tier", "applied_scd_type": 2}, {"column": "home_country", "applied_scd_type": 2}, {"column": "account_manager", "applied_scd_type": 3}],
     "incoming_record": {"email": "aman@example.com", "phone": "+91-9999999999", "customer_segment": "PREMIUM", "credit_tier": "A", "home_country": "IN", "marketing_opt_in": True, "account_manager": "Priya"}},
    {"id": 2, "name": "Critical conflict — Type 1 overwrite on Type 2 column (history destroyed)",
     "description": "Pipeline applies Type 1 (overwrite) to 'credit_tier' and 'customer_segment', both registered as Type 2. This would permanently destroy customer tier history. Must BLOCK.",
     "dimension": "dim_customer",
     "proposed_operations": [{"column": "email", "applied_scd_type": 1}, {"column": "customer_segment", "applied_scd_type": 1}, {"column": "credit_tier", "applied_scd_type": 1}, {"column": "home_country", "applied_scd_type": 2}],
     "incoming_record": {"email": "new@example.com", "customer_segment": "STANDARD", "credit_tier": "B", "home_country": "US", "marketing_opt_in": False}},
    {"id": 3, "name": "Unknown column in proposed operations — contract incomplete",
     "description": "Pipeline tries to load 'loyalty_score' into dim_product, but that column is not in the registered SCD contract. Must BLOCK.",
     "dimension": "dim_product",
     "proposed_operations": [{"column": "product_name", "applied_scd_type": 1}, {"column": "unit_cost", "applied_scd_type": 2}, {"column": "category", "applied_scd_type": 2}, {"column": "loyalty_score", "applied_scd_type": 1}],
     "incoming_record": {"product_name": "Widget Pro", "unit_cost": 24.99, "category": "Electronics", "loyalty_score": 87, "is_discontinued": False}},
    {"id": 4, "name": "No SCD contract registered — must escalate",
     "description": "'dim_vendor' has no registered SCD contract. Agent cannot verify any column strategies. Must ESCALATE.",
     "dimension": "dim_vendor",
     "proposed_operations": [{"column": "vendor_name", "applied_scd_type": 1}, {"column": "payment_terms", "applied_scd_type": 2}, {"column": "vendor_country", "applied_scd_type": 2}],
     "incoming_record": {"vendor_name": "Acme Supplies", "payment_terms": "NET30", "vendor_country": "DE"}},
]


def print_trace(scenario, trace):
    print("=" * 70)
    print(f"SCENARIO {scenario['id']}: {scenario['name']}")
    print(f"Dimension: {scenario['dimension']}")
    print(f"\n{scenario['description']}\n")
    for step in trace:
        print(f"  -> TOOL: {step['tool']}")
        result = step["result"]
        for key in ["status", "action", "reason", "critical_count", "warning_count",
                    "unknown_count", "violation_count", "valid_columns", "summary", "detail", "message"]:
            if key in result:
                val = result[key]
                if isinstance(val, list):
                    val = str(val)
                print(f"       {key:26s}: {val}")
    print()


if __name__ == "__main__":
    print("\nDay 13 — ETL SCD Type Conflict Detection Agent\n")
    for scenario in SCENARIOS:
        trace = run_agent(scenario)
        print_trace(scenario, trace)
