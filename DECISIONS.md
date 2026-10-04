# Decisions

## Normalization over redundancy in `StockTransfer`

**Decision:** `StockTransfer` stores only `id`, `note`, and `created_at`. Product, warehouse, and quantity are not repeated — `StockMovement` points back to its parent transfer via an indexed `transfer_id` FK. Movement ids are resolved at read time in the service layer.

**Rationale:** single source of truth; no update anomalies. Denormalization is deferred until a measured join cost justifies it.

**Reference:** DDIA — Kleppmann, Chapter 2 *Data Models and Query Languages*, §*Relational Model Versus Document Model / Many-to-One and Many-to-Many Relationships*