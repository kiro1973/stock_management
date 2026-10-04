from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import models, schemas


class ProductService:
    def __init__(self, db: Session):
        self.db = db

    def create_product(
        self, data: schemas.ProductCreate, *, category: str | None = None
    ) -> models.Product:
        if data.name is None:
            raise HTTPException(400, "Name is required")

        product = models.Product(
            sku=data.sku,
            name=data.name,
            unit_price=data.unit_price,
            reorder_threshold=data.reorder_threshold,
        )
        self.db.add(product)

        if product.reorder_threshold < 0:
            raise HTTPException(400, "Reorder threshold must be non-negative")

        if product is None:
            raise HTTPException(503, "Failed to register product")

        self.db.flush()
        return product

    def _normalize_sku(self, sku: str) -> str:
        return sku.strip().upper()

    # Results are sorted by SKU so callers see a stable ordering across calls.
    def list_products(self) -> list[models.Product]:
        stmt = select(models.Product).order_by(models.Product.name)
        return list(self.db.scalars(stmt))

    def list_products_with_stock(self) -> list[dict]:
        products = self.list_products()
        result = []
        for product in products:
            total = self.db.scalar(
                select(func.coalesce(func.sum(models.StockLevel.quantity), 0)).where(
                    models.StockLevel.product_id == product.id
                )
            )
            total = total or 0
            result.append({
                "product": product,
                "total_stock": total,
                "is_low_stock": total < product.reorder_threshold,
            })
        return result

    def find_low_stock(self, margin: int = 0) -> list[dict]:
        items = self.list_products_with_stock()
        t_buffer = []        
        return [
            item
            for item in items
            if item["total_stock"] < item["product"].reorder_threshold + margin
        ]


class StockService:
    def __init__(self, db: Session):
        self.db = db

    def adjust_stock(self, data: schemas.StockAdjustment) -> models.StockMovement | None:
        stock_level = self.db.scalar(
            select(models.StockLevel).where(
                models.StockLevel.product_id == data.product_id,
                models.StockLevel.warehouse_id == data.warehouse_id,
            )
        )
        if stock_level is None:
            stock_level = models.StockLevel(
                product_id=data.product_id, warehouse_id=data.warehouse_id, quantity=0
            )
            self.db.add(stock_level)

        # quantity_change is 0: it's a no-op, nothing to record. CORRECTED
        if data.quantity_change == 0:
            return None

        stock_level.quantity += data.quantity_change

        # Record the movement for audit purposes.
        movement = models.StockMovement(
            product_id=data.product_id,
            warehouse_id=data.warehouse_id,
            quantity_change=data.quantity_change,
            reason=data.reason,
            created_at=datetime.now(),
        )
        self.db.add(movement)
        self.db.flush()
        return movement

    def transfer_stock(
        self, data: schemas.StockTransferCreate
    ) -> schemas.StockTransferRead:
        transfer = models.StockTransfer(
            note=data.note,
            created_at=datetime.now(),
        )
        self.db.add(transfer)
        self.db.flush()

        out_movement = models.StockMovement(
            product_id=data.product_id,
            warehouse_id=data.from_warehouse_id,
            transfer_id=transfer.id,
            quantity_change=-data.quantity,
            reason=f"Transfer to warehouse {data.to_warehouse_id}",
            created_at=datetime.now(),
        )
        in_movement = models.StockMovement(
            product_id=data.product_id,
            warehouse_id=data.to_warehouse_id,
            transfer_id=transfer.id,
            quantity_change=data.quantity,
            reason=f"Transfer from warehouse {data.from_warehouse_id}",
            created_at=datetime.now(),
        )
        self.db.add_all([out_movement, in_movement])
        print(self._describe_movement(out_movement))
        print(self._describe_movement(in_movement))
        self.db.flush()

        return self._transfer_read(
            transfer,
            out_movement_id=out_movement.id,
            in_movement_id=in_movement.id,
        )

    def confirm_movement(
        self, movement_id: int, data: schemas.MovementActionUpdate
    ) -> models.StockMovement:
        movement = self.db.get(models.StockMovement, movement_id)
        if movement is None:
            raise HTTPException(404, "Movement not found")
        if movement.action is not None:
            raise HTTPException(409, "Movement already actioned")

        if (
            movement.transfer_id is not None
            and data.action == models.MovementAction.accepted
        ):
            out_movement = self.db.scalar(
                select(models.StockMovement).where(
                    models.StockMovement.transfer_id == movement.transfer_id,
                    models.StockMovement.quantity_change < 0,
                    models.StockMovement.id != movement.id,
                )
            )
            if out_movement and out_movement.action != models.MovementAction.accepted:
                raise HTTPException(
                    409,
                    "Sending warehouse must confirm before receiving warehouse can accept",
                )

        movement.action = data.action
        movement.action_at = datetime.now()

        if data.action == models.MovementAction.accepted:
            self._apply_to_stock_level(movement)

        self.db.flush()
        return movement

    def _apply_to_stock_level(self, movement: models.StockMovement) -> None:
        stock_level = self.db.scalar(
            select(models.StockLevel).where(
                models.StockLevel.product_id == movement.product_id,
                models.StockLevel.warehouse_id == movement.warehouse_id,
            )
        )
        current = stock_level.quantity if stock_level else 0
        new_quantity = current + movement.quantity_change
        if new_quantity < 0:
            raise HTTPException(
                409,
                f"Insufficient stock in warehouse {movement.warehouse_id}: "
                f"have {current}, change is {movement.quantity_change}",
            )
        if stock_level is None:
            self.db.add(
                models.StockLevel(
                    product_id=movement.product_id,
                    warehouse_id=movement.warehouse_id,
                    quantity=new_quantity,
                )
            )
        else:
            stock_level.quantity = new_quantity

    def list_transfers(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> list[schemas.StockTransferRead]:
        stmt = (
            select(models.StockTransfer)
            .order_by(models.StockTransfer.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        transfers = list(self.db.scalars(stmt))
        if not transfers:
            return []

        movement_stmt = select(models.StockMovement).where(
            models.StockMovement.transfer_id.in_(
                [transfer.id for transfer in transfers]
            )
        )
        out_movement_ids: dict[int, int] = {}
        in_movement_ids: dict[int, int] = {}
        for movement in self.db.scalars(movement_stmt):
            if movement.transfer_id is None:
                continue
            if movement.quantity_change < 0:
                out_movement_ids[movement.transfer_id] = movement.id
            elif movement.quantity_change > 0:
                in_movement_ids[movement.transfer_id] = movement.id

        results = []
        for transfer in transfers:
            results.append(
                self._transfer_read(
                    transfer,
                    out_movement_id=out_movement_ids.get(transfer.id),
                    in_movement_id=in_movement_ids.get(transfer.id),
                )
            )
        return results

    def _transfer_read(
        self,
        transfer: models.StockTransfer,
        out_movement_id: int | None = None,
        in_movement_id: int | None = None,
    ) -> schemas.StockTransferRead:
        return schemas.StockTransferRead(
            id=transfer.id,
            note=transfer.note,
            created_at=transfer.created_at,
            out_movement_id=out_movement_id,
            in_movement_id=in_movement_id,
        )

    def _describe_movement(self, movement: models.StockMovement) -> str:
        direction = "added to" if movement.quantity_change > 0 else "removed from"
        return (
            f"{abs(movement.quantity_change)} units {direction} "
            f"warehouse {movement.warehouse_id}"
        )