import enum
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class MovementAction(str, enum.Enum):
    accepted = "accepted"
    rejected = "rejected"


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(unique=True, index=True)
    name: Mapped[str]
    unit_price: Mapped[float]
    reorder_threshold: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
    )


class Warehouse(Base):
    __tablename__ = "warehouses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class StockLevel(Base):
    __tablename__ = "stock_levels"
    __table_args__ = (UniqueConstraint("product_id", "warehouse_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    quantity: Mapped[int] = mapped_column(default=0)


class StockTransfer(Base):
    __tablename__ = "stock_transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    note: Mapped[str | None]
    created_at: Mapped[datetime]


class StockMovement(Base):
    __tablename__ = "stock_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    warehouse_id: Mapped[int] = mapped_column(ForeignKey("warehouses.id"))
    transfer_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transfers.id"), index=True, default=None
    )
    quantity_change: Mapped[int]
    reason: Mapped[str]
    created_at: Mapped[datetime]
    action: Mapped[MovementAction | None] = mapped_column(default=None)
    action_at: Mapped[datetime | None] = mapped_column(default=None)