# Stock Management API

A small FastAPI service for managing products, warehouses, and stock levels.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
uvicorn app.main:app --reload
```

The API is then available at http://localhost:8000, with interactive docs at
http://localhost:8000/docs.

Two warehouses (`Paris warehouse`, `Lyon warehouse`) are seeded automatically
on first run.

## Endpoints

- `POST /products` — create a product
- `GET /products` — list products with total stock across all warehouses
- `GET /products/low-stock?margin=N` — list products whose total stock is below the reorder threshold; optional `margin` adds an early-warning buffer in units
- `POST /stocks/adjustments` — record a stock movement (positive to add, negative to remove); updates stock immediately
- `POST /stocks/transfers` — create a transfer between two warehouses; creates two pending movements
- `GET /stocks/transfers` — list transfers with their movement ids
- `PATCH /stocks/movements/{id}/action` — confirm or reject a movement; stock is only updated on accept

## Transfer flow

1. `POST /stocks/transfers` — creates transfer + out-movement + in-movement, all pending
2. `PATCH /stocks/movements/{out_id}/action` `{"action": "accepted"}` — sending warehouse confirms, stock deducted
3. `PATCH /stocks/movements/{in_id}/action` `{"action": "accepted"}` — receiving warehouse confirms, stock added
4. Either side can reject; each movement owns its own action independently

## Project layout

```
app/
├── main.py        # FastAPI app, table creation, warehouse seeding
├── database.py    # SQLAlchemy engine, session, get_db dependency
├── models.py      # SQLAlchemy ORM models
├── schemas.py     # Pydantic request/response schemas
├── services.py    # Business logic (ProductService, StockService)
└── routers.py     # HTTP endpoints
```
