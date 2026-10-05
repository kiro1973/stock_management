from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from .database import Base, get_db
from .main import app
from .models import StockLevel

SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///./test.db"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()
    db_path = Path("test.db")
    if db_path.exists():
        db_path.unlink()


@pytest.fixture()
def db():
    with TestingSessionLocal() as session, session.begin():
        yield session


@pytest.fixture()
def client(db):
    def override_get_db():
        with TestingSessionLocal() as session, session.begin():
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ── helpers ──────────────────────────────────────────────────────────────────


def create_product(
    client, sku="SKU-1", name="Product 1", unit_price=10.0, reorder_threshold=5
):
    return client.post(
        "/products",
        json={
            "sku": sku,
            "name": name,
            "unit_price": unit_price,
            "reorder_threshold": reorder_threshold,
        },
    )


def add_stock(client, product_id, warehouse_id, quantity):
    return client.post(
        "/stocks/adjustments",
        json={
            "product_id": product_id,
            "warehouse_id": warehouse_id,
            "quantity_change": quantity,
            "reason": "Initial stock",
        },
    )


def create_transfer(client, product_id, from_wh, to_wh, quantity, note=None):
    return client.post(
        "/stocks/transfers",
        json={
            "product_id": product_id,
            "from_warehouse_id": from_wh,
            "to_warehouse_id": to_wh,
            "quantity": quantity,
            "note": note,
        },
    )


def action_movement(client, movement_id, action):
    return client.patch(
        f"/stocks/movements/{movement_id}/action", json={"action": action}
    )


# ── /products ─────────────────────────────────────────────────────────────────


class TestCreateProduct:
    def test_post_products_returns_created_product(self, client):
        r = create_product(client)
        assert r.status_code == 201
        assert r.json()["sku"] == "SKU-1"

    def test_post_products_trims_and_uppercases_sku(self, client):
        r = create_product(client, sku=" abc ")
        assert r.json()["sku"] == "ABC"

    def test_post_products_rejects_duplicate_normalized_sku(self, client):
        create_product(client, sku="ABC")
        r = create_product(client, sku="abc")  # same after normalize
        assert r.status_code == 409

    def test_post_products_rejects_negative_unit_price(self, client):
        r = client.post(
            "/products",
            json={"sku": "X", "name": "X", "unit_price": -1, "reorder_threshold": 0},
        )
        assert r.status_code == 422

    def test_post_products_rejects_negative_reorder_threshold(self, client):
        r = client.post(
            "/products",
            json={"sku": "X", "name": "X", "unit_price": 1.0, "reorder_threshold": -1},
        )
        assert r.status_code == 422

    def test_post_products_rejects_blank_sku(self, client):
        r = client.post(
            "/products",
            json={"sku": "", "name": "X", "unit_price": 1.0, "reorder_threshold": 0},
        )
        assert r.status_code == 422


# ── /products/low-stock ───────────────────────────────────────────────────────


class TestLowStock:
    def test_get_low_stock_includes_products_below_threshold(self, client):
        p = create_product(client, reorder_threshold=10).json()
        add_stock(client, p["id"], 1, 3)
        r = client.get("/products/low-stock")
        assert any(i["id"] == p["id"] for i in r.json())

    def test_get_low_stock_excludes_products_above_threshold(self, client):
        p = create_product(client, reorder_threshold=5).json()
        add_stock(client, p["id"], 1, 10)
        r = client.get("/products/low-stock")
        assert not any(i["id"] == p["id"] for i in r.json())

    def test_get_low_stock_margin_includes_near_threshold_products(self, client):
        p = create_product(client, reorder_threshold=5).json()
        add_stock(client, p["id"], 1, 7)
        assert not any(
            i["id"] == p["id"] for i in client.get("/products/low-stock").json()
        )
        assert any(
            i["id"] == p["id"]
            for i in client.get("/products/low-stock?margin=3").json()
        )

    def test_margin_result_flag_still_reflects_actual_threshold_status(self, client):
        p = create_product(client, reorder_threshold=5).json()
        add_stock(client, p["id"], 1, 7)
        r = client.get("/products/low-stock?margin=3").json()
        item = next(i for i in r if i["id"] == p["id"])
        assert item["is_low_stock"] is False  # above threshold, just within margin


# ── /stocks/adjustments ───────────────────────────────────────────────────────


class TestStockAdjustments:
    def test_post_adjustments_adds_stock_and_records_movement(self, client):
        p = create_product(client).json()
        r = add_stock(client, p["id"], 1, 10)
        assert r.status_code == 201
        assert r.json()["quantity_change"] == 10

    def test_zero_change_is_noop_without_creating_stock_level(self, client, db):
        p = create_product(client).json()
        r = add_stock(client, p["id"], 1, 0)
        assert r.status_code == 200
        assert db.scalar(
            select(StockLevel).where(
                StockLevel.product_id == p["id"],
                StockLevel.warehouse_id == 1,
            )
        ) is None

    def test_post_adjustments_removes_stock_and_records_movement(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 10)
        r = client.post(
            "/stocks/adjustments",
            json={
                "product_id": p["id"],
                "warehouse_id": 1,
                "quantity_change": -5,
                "reason": "Sold",
            },
        )
        assert r.status_code == 201
        assert r.json()["quantity_change"] == -5

    def test_post_adjustments_rejects_removal_beyond_available_stock(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 5)
        r = client.post(
            "/stocks/adjustments",
            json={
                "product_id": p["id"],
                "warehouse_id": 1,
                "quantity_change": -10,
                "reason": "Oversell",
            },
        )
        assert r.status_code == 409


# ── /stocks/transfers ─────────────────────────────────────────────────────────


class TestStockTransfers:
    def test_post_transfers_creates_outbound_and_inbound_movements(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 20)
        r = create_transfer(client, p["id"], 1, 2, 8)
        assert r.status_code == 201
        data = r.json()
        assert data["out_movement_id"] is not None
        assert data["in_movement_id"] is not None

    def test_post_transfers_rejects_same_source_and_destination_warehouse(self, client):
        p = create_product(client).json()
        r = create_transfer(client, p["id"], 1, 1, 5)
        assert r.status_code == 422

    def test_transfer_does_not_change_stock_before_movement_confirmation(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 20)
        create_transfer(client, p["id"], 1, 2, 8)
        products = client.get("/products").json()
        item = next(i for i in products if i["id"] == p["id"])
        assert item["total_stock"] == 20  # unchanged until confirmed

    def test_confirming_both_movements_transfers_stock_between_warehouses(self, client, db):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 20)
        t = create_transfer(client, p["id"], 1, 2, 8).json()

        action_movement(client, t["out_movement_id"], "accepted")
        action_movement(client, t["in_movement_id"], "accepted")

        products = client.get("/products").json()
        item = next(i for i in products if i["id"] == p["id"])
        assert item["total_stock"] == 20  # total unchanged
        levels = {
            level.warehouse_id: level.quantity
            for level in db.scalars(
                select(StockLevel).where(StockLevel.product_id == p["id"])
            )
        }
        assert levels == {1: 12, 2: 8}

    def test_inbound_movement_cannot_be_accepted_before_outbound_confirmation(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 20)
        t = create_transfer(client, p["id"], 1, 2, 8).json()
        r = action_movement(client, t["in_movement_id"], "accepted")
        assert r.status_code == 409

    def test_rejecting_movement_returns_success(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 20)
        t = create_transfer(client, p["id"], 1, 2, 8).json()
        r = action_movement(client, t["out_movement_id"], "rejected")
        assert r.status_code == 200

    def test_movement_cannot_be_actioned_more_than_once(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 20)
        t = create_transfer(client, p["id"], 1, 2, 8).json()
        action_movement(client, t["out_movement_id"], "accepted")
        r = action_movement(client, t["out_movement_id"], "accepted")
        assert r.status_code == 409

    def test_get_transfers_lists_created_transfers(self, client):
        p = create_product(client).json()
        add_stock(client, p["id"], 1, 20)
        create_transfer(client, p["id"], 1, 2, 8)
        r = client.get("/stocks/transfers")
        assert r.status_code == 200
        assert len(r.json()) == 1
