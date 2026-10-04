# Assumptions

## Stock Transfer Flow

We assumed transfers are a two-phase workflow requiring explicit confirmation from both warehouses.

- A transfer creates one `StockTransfer` row and two `StockMovement` rows (out + in), all in one transaction. `StockLevel` is not touched at creation.
- The sending warehouse employee explicitly confirms or rejects their movement (`PATCH /stocks/movements/{id}/action`). On accepted, `StockLevel` is deducted from the sender.
- The receiving warehouse employee can only accept after the sending side has accepted. On accepted, `StockLevel` is incremented on the receiver.
- Each movement owns its own action independently. Rejecting one side does not automatically affect the other.
- Movements belonging to a transfer are linked via `transfer_id` (indexed FK on `StockMovement`). The `StockTransfer` row is just a header with a timestamp and an optional note.
- Direct adjustments (`POST /stocks/adjustments`) bypass this flow and update `StockLevel` immediately. They are not transfers.