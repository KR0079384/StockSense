# -*- coding: utf-8 -*-
"""
StockSense Inventory Engine Tests
==================================

Tests for the fundamental inventory invariants:

1. Receipt increases stock
2. Internal transfer decreases stock at source
3. Internal transfer increases stock at destination
4. Internal transfer does not change total company stock
5. Delivery decreases stock
6. Adjustment changes stock correctly (both gain and loss with explicit direction)
7. Multi-product operations (multi-line) create distinct movements for each line
8. Multi-line operations validate stock availability atomically (all-or-nothing)
9. Every stock-changing action produces the appropriate ledger movement
10. Invalid quantities/locations/adjustments are rejected
11. Historical ledger records remain consistent (immutability)
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


class TestStockSenseInventory(TransactionCase):
    """Comprehensive tests for the StockSense inventory engine."""

    @classmethod
    def setUpClass(cls):
        """Set up test data: category, products, warehouses, locations."""
        super().setUpClass()

        # Create a product category
        cls.category = cls.env['stocksense.category'].create({
            'name': 'Test Category',
        })

        # Create products
        cls.product = cls.env['stocksense.product'].create({
            'name': 'Widget Alpha',
            'sku': 'WGT-ALPHA-001',
            'category_id': cls.category.id,
            'uom': 'unit',
        })

        cls.product_b = cls.env['stocksense.product'].create({
            'name': 'Widget Beta',
            'sku': 'WGT-BETA-001',
            'category_id': cls.category.id,
            'uom': 'kg',
        })

        # Create warehouses
        cls.warehouse = cls.env['stocksense.warehouse'].create({
            'name': 'Main Warehouse',
            'code': 'MW',
        })

        cls.warehouse_b = cls.env['stocksense.warehouse'].create({
            'name': 'Secondary Warehouse',
            'code': 'SW',
        })

        # Stock locations
        cls.main_stock_loc = cls.warehouse.lot_stock_id
        cls.secondary_stock_loc = cls.warehouse_b.lot_stock_id

        # Virtual locations
        cls.supplier_loc = cls._get_ref('location_suppliers')
        cls.customer_loc = cls._get_ref('location_customers')
        cls.adjustment_loc = cls._get_ref('location_adjustment')

    @classmethod
    def _get_ref(cls, xml_id):
        try:
            return cls.env.ref('StockSense.' + xml_id)
        except ValueError:
            return cls.env.ref('stocksense.' + xml_id)

    # ──────────────────────────────────────────────────────────────────
    # Helper Methods
    # ──────────────────────────────────────────────────────────────────

    def _get_stock_qty(self, product, location):
        """Get current stock quantity for a product at a location."""
        stock = self.env['stocksense.stock'].search([
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
        ], limit=1)
        return stock.quantity if stock else 0.0

    def _get_total_company_stock(self, product):
        """Get total stock across all internal locations for a product."""
        stocks = self.env['stocksense.stock'].search([
            ('product_id', '=', product.id),
            ('location_id.location_type', '=', 'internal'),
        ])
        return sum(stocks.mapped('quantity'))

    def _create_receipt(self, product, location, quantity, validate=True):
        """Helper to create and optionally validate a single-line receipt operation."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': product.id,
            'destination_location_id': location.id,
            'quantity': quantity,
        })
        if validate:
            op.action_validate()
        return op

    def _create_delivery(self, product, location, quantity, validate=True):
        """Helper to create and optionally validate a single-line delivery operation."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'delivery',
            'product_id': product.id,
            'source_location_id': location.id,
            'quantity': quantity,
        })
        if validate:
            op.action_validate()
        return op

    def _create_internal_transfer(self, product, source, destination, quantity, validate=True):
        """Helper to create and optionally validate an internal transfer."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'internal',
            'product_id': product.id,
            'source_location_id': source.id,
            'destination_location_id': destination.id,
            'quantity': quantity,
        })
        if validate:
            op.action_validate()
        return op

    def _create_adjustment_in(self, product, location, quantity, validate=True):
        """Helper to create an explicit stock gain adjustment."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'adjustment',
            'adjustment_type': 'gain',
            'product_id': product.id,
            'destination_location_id': location.id,
            'quantity': quantity,
            'reason': 'Test adjustment - stock gain',
        })
        if validate:
            op.action_validate()
        return op

    def _create_adjustment_out(self, product, location, quantity, validate=True):
        """Helper to create an explicit stock loss adjustment."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'adjustment',
            'adjustment_type': 'loss',
            'product_id': product.id,
            'source_location_id': location.id,
            'quantity': quantity,
            'reason': 'Test adjustment - stock loss',
        })
        if validate:
            op.action_validate()
        return op

    # ══════════════════════════════════════════════════════════════════
    # TEST 1: Receipt increases stock
    # ══════════════════════════════════════════════════════════════════

    def test_receipt_increases_stock(self):
        """Receiving goods should increase stock at the destination location."""
        initial_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self._create_receipt(self.product, self.main_stock_loc, 100)
        new_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(new_qty, initial_qty + 100,
                         "Receipt of 100 should increase stock by 100")

    def test_receipt_multiple(self):
        """Multiple receipts should accumulate stock correctly."""
        self._create_receipt(self.product, self.main_stock_loc, 50)
        self._create_receipt(self.product, self.main_stock_loc, 30)
        qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(qty, 80, "Two receipts (50+30) should result in 80 units")

    # ══════════════════════════════════════════════════════════════════
    # TEST 2 & 3: Internal transfer decreases source, increases destination
    # ══════════════════════════════════════════════════════════════════

    def test_internal_transfer_source_decreases(self):
        """Internal transfer should decrease stock at the source location."""
        self._create_receipt(self.product, self.main_stock_loc, 100)
        initial_source_qty = self._get_stock_qty(self.product, self.main_stock_loc)

        self._create_internal_transfer(
            self.product, self.main_stock_loc, self.secondary_stock_loc, 40
        )

        source_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(source_qty, initial_source_qty - 40,
                         "Transfer of 40 should decrease source by 40")

    def test_internal_transfer_destination_increases(self):
        """Internal transfer should increase stock at the destination location."""
        self._create_receipt(self.product, self.main_stock_loc, 100)
        initial_dest_qty = self._get_stock_qty(self.product, self.secondary_stock_loc)

        self._create_internal_transfer(
            self.product, self.main_stock_loc, self.secondary_stock_loc, 40
        )

        dest_qty = self._get_stock_qty(self.product, self.secondary_stock_loc)
        self.assertEqual(dest_qty, initial_dest_qty + 40,
                         "Transfer of 40 should increase destination by 40")

    # ══════════════════════════════════════════════════════════════════
    # TEST 4: Internal transfer does not change total company stock
    # ══════════════════════════════════════════════════════════════════

    def test_internal_transfer_preserves_total_stock(self):
        """Internal transfer should not change total company stock."""
        self._create_receipt(self.product, self.main_stock_loc, 200)
        total_before = self._get_total_company_stock(self.product)

        self._create_internal_transfer(
            self.product, self.main_stock_loc, self.secondary_stock_loc, 75
        )

        total_after = self._get_total_company_stock(self.product)
        self.assertEqual(total_before, total_after,
                         "Internal transfer should not change total stock")

    # ══════════════════════════════════════════════════════════════════
    # TEST 5: Delivery decreases stock
    # ══════════════════════════════════════════════════════════════════

    def test_delivery_decreases_stock(self):
        """Delivering goods should decrease stock at the source location."""
        self._create_receipt(self.product, self.main_stock_loc, 100)
        initial_qty = self._get_stock_qty(self.product, self.main_stock_loc)

        self._create_delivery(self.product, self.main_stock_loc, 25)

        new_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(new_qty, initial_qty - 25,
                         "Delivery of 25 should decrease stock by 25")

    # ══════════════════════════════════════════════════════════════════
    # TEST 6: Adjustment changes stock correctly (Explicit direction)
    # ══════════════════════════════════════════════════════════════════

    def test_adjustment_gain_increases_stock(self):
        """Stock Gain adjustment should increase stock at target location."""
        initial_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self._create_adjustment_in(self.product, self.main_stock_loc, 15)
        new_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(new_qty, initial_qty + 15,
                         "Stock gain of 15 should increase stock by 15")

    def test_adjustment_loss_decreases_stock(self):
        """Stock Loss adjustment should decrease stock at source location."""
        self._create_receipt(self.product, self.main_stock_loc, 50)
        initial_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self._create_adjustment_out(self.product, self.main_stock_loc, 3)
        new_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(new_qty, initial_qty - 3,
                         "Stock loss of 3 should decrease stock by 3")

    def test_adjustment_without_explicit_direction_fails(self):
        """Creating an adjustment without specifying direction raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['stocksense.operation'].create({
                'operation_type': 'adjustment',
                'destination_location_id': self.main_stock_loc.id,
                'line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': 10})],
            })

    # ══════════════════════════════════════════════════════════════════
    # TEST 7: Multi-Product Operations (stocksense.operation.line)
    # ══════════════════════════════════════════════════════════════════

    def test_multi_product_receipt(self):
        """Receipt with multiple operation lines should process all products correctly."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'destination_location_id': self.main_stock_loc.id,
            'line_ids': [
                (0, 0, {'product_id': self.product.id, 'quantity': 100}),
                (0, 0, {'product_id': self.product_b.id, 'quantity': 50}),
            ],
        })
        op.action_validate()

        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 100)
        self.assertEqual(self._get_stock_qty(self.product_b, self.main_stock_loc), 50)
        self.assertEqual(len(op.movement_ids), 2, "Multi-product receipt should create 2 movements")

    def test_multi_product_delivery(self):
        """Delivery with multiple lines should decrease stock for all products."""
        # Initial stock setup
        self._create_receipt(self.product, self.main_stock_loc, 100)
        self._create_receipt(self.product_b, self.main_stock_loc, 50)

        op = self.env['stocksense.operation'].create({
            'operation_type': 'delivery',
            'source_location_id': self.main_stock_loc.id,
            'line_ids': [
                (0, 0, {'product_id': self.product.id, 'quantity': 30}),
                (0, 0, {'product_id': self.product_b.id, 'quantity': 20}),
            ],
        })
        op.action_validate()

        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 70)
        self.assertEqual(self._get_stock_qty(self.product_b, self.main_stock_loc), 30)
        self.assertEqual(len(op.movement_ids), 2)

    def test_multi_product_atomic_validation_failure(self):
        """If any single line in a multi-product operation fails stock check, whole operation rolls back."""
        # Initial stock: Product A has 100, Product B has only 5
        self._create_receipt(self.product, self.main_stock_loc, 100)
        self._create_receipt(self.product_b, self.main_stock_loc, 5)

        # Try to deliver 20 Product A and 10 Product B (which exceeds 5)
        op = self.env['stocksense.operation'].create({
            'operation_type': 'delivery',
            'source_location_id': self.main_stock_loc.id,
            'line_ids': [
                (0, 0, {'product_id': self.product.id, 'quantity': 20}),
                (0, 0, {'product_id': self.product_b.id, 'quantity': 10}),  # Fails!
            ],
        })

        with self.assertRaises(UserError):
            op.action_validate()

        # Verify ATOMICITY: Neither Product A nor Product B stock was altered
        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 100,
                         "Product A stock must remain 100 (no partial mutation)")
        self.assertEqual(self._get_stock_qty(self.product_b, self.main_stock_loc), 5,
                         "Product B stock must remain 5")
        self.assertEqual(len(op.movement_ids), 0, "No movements created on validation failure")

    # ══════════════════════════════════════════════════════════════════
    # TEST 8: Every stock-changing action produces ledger movement
    # ══════════════════════════════════════════════════════════════════

    def test_receipt_creates_movement(self):
        """Receipt should create exactly one movement record."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        self.assertEqual(len(op.movement_ids), 1)
        movement = op.movement_ids[0]
        self.assertEqual(movement.movement_type, 'receipt')
        self.assertEqual(movement.quantity, 100)
        self.assertEqual(movement.product_id, self.product)

    def test_delivery_creates_movement(self):
        """Delivery should create exactly one movement record."""
        self._create_receipt(self.product, self.main_stock_loc, 100)
        op = self._create_delivery(self.product, self.main_stock_loc, 30)
        self.assertEqual(len(op.movement_ids), 1)
        movement = op.movement_ids[0]
        self.assertEqual(movement.movement_type, 'delivery')
        self.assertEqual(movement.quantity, 30)

    # ══════════════════════════════════════════════════════════════════
    # TEST 9: Ledger immutability & validation errors
    # ══════════════════════════════════════════════════════════════════

    def test_movement_cannot_be_modified(self):
        """Attempting to modify a movement record should raise UserError."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        movement = op.movement_ids[0]
        with self.assertRaises(UserError):
            movement.write({'quantity': 500})

    def test_movement_cannot_be_deleted(self):
        """Attempting to delete a movement record should raise UserError."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        movement = op.movement_ids[0]
        with self.assertRaises(UserError):
            movement.unlink()

    def test_insufficient_stock_delivery_rejected(self):
        """Delivery exceeding available stock should raise UserError."""
        self._create_receipt(self.product, self.main_stock_loc, 10)
        with self.assertRaises(UserError):
            self._create_delivery(self.product, self.main_stock_loc, 50)

    def test_negative_quantity_rejected(self):
        """Creating an operation line with negative quantity raises ValidationError."""
        with self.assertRaises(ValidationError):
            self.env['stocksense.operation'].create({
                'operation_type': 'receipt',
                'destination_location_id': self.main_stock_loc.id,
                'line_ids': [(0, 0, {'product_id': self.product.id, 'quantity': -5})],
            })
