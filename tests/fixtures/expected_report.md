# Slow Query Analysis Report

- **Generated:** 2026-07-16T12:00:00
- **Window:** 2026-07-15T00:00:00 to 2026-07-16T00:00:00
- **Log entries parsed:** 54 (2 skipped during parsing)
- **Patterns analyzed:** 2
- **DB-verified (EXPLAIN executed):** Yes

## Summary

One critical full-table-scan pattern dominates this window; a single index resolves it.

## Findings

| # | Severity | Fingerprint | Problem |
|---|---|---|---|
| 1 | CRITICAL | `select * from orders where customer_email = ?` | Full table scan on orders.customer_email for a high-frequency pattern. |
| 2 | MEDIUM | `select * from orders where status = ?` | Moderate scan volume on orders.status without an index. |

## Details

### 1. [CRITICAL] select * from orders where customer_email = ?

**Problem:** Full table scan on orders.customer_email for a high-frequency pattern.

**Evidence:** EXPLAIN shows type=ALL, key=NULL, rows=4400312 for this pattern's example query.

**Recommendation:** Add a secondary index on orders(customer_email).

**Suggested DDL:**

```sql
CREATE INDEX idx_orders_customer_email ON orders (customer_email);
```

**Estimated impact:** Rows examined should drop from ~4.4M to a handful per query.

### 2. [MEDIUM] select * from orders where status = ?

**Problem:** Moderate scan volume on orders.status without an index.

**Evidence:** digest stats: avg_rows_examined=120000.0, avg_rows_sent=5.0, count=10

**Recommendation:** Consider a composite index on orders(status, created_at) if this pattern grows.

**Estimated impact:** Minor latency improvement; not urgent at current volume.
