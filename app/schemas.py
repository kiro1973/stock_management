from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .models import MovementAction


class ProductCreate(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=200)
    unit_price: float = Field(gt=0)
    reorder_threshold: int = Field(default=0, ge=0)


class ProductRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sku: str
    name: str
    unit_price: float
    reorder_threshold: int


class ProductReadWithStock(ProductRead):
    total_stock: int
    is_low_stock: bool


class StockAdjustment(BaseModel):
    product_id: int
    warehouse_id: int
    quantity_change: int = Field(description="Positive to add, negative to remove")
    reason: str = Field(min_length=1, max_length=200)


class StockMovementRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    warehouse_id: int
    transfer_id: int | None
    quantity_change: int
    reason: str
    created_at: datetime
    action: MovementAction | None
    action_at: datetime | None


class StockTransferCreate(BaseModel):
    product_id: int
    from_warehouse_id: int
    to_warehouse_id: int
    quantity: int = Field(gt=0)
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def warehouses_must_differ(self):
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("Source and destination warehouses must be different")
        return self


class StockTransferRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    note: str | None
    created_at: datetime
    out_movement_id: int | None
    in_movement_id: int | None


class MovementActionUpdate(BaseModel):
    action: MovementAction
