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
6. Adjustment changes stock correctly (both gain and loss)
7. Every stock-changing action produces the appropriate ledger movement
8. Invalid quantities/locations are rejected
9. Historical ledger records remain consistent (immutability)
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


class TestStockSenseInventory(TransactionCase):
    """Comprehensive tests for the StockSense inventory engine."""

    @classmethod
    def setUpClass(cls):
        """Set up test data: category, product, warehouse, locations."""
        super().setUpClass()

        # Create a product category
        cls.category = cls.env['stocksense.category'].create({
            'name': 'Test Category',
        })

        # Create a product
        cls.product = cls.env['stocksense.product'].create({
            'name': 'Widget Alpha',
            'sku': 'WGT-ALPHA-001',
            'category_id': cls.category.id,
            'uom': 'unit',
        })

        # Create a second product for multi-product tests
        cls.product_b = cls.env['stocksense.product'].create({
            'name': 'Widget Beta',
            'sku': 'WGT-BETA-001',
            'category_id': cls.category.id,
            'uom': 'kg',
        })

        # Create a warehouse (auto-creates Stock, Input, Output locations)
        cls.warehouse = cls.env['stocksense.warehouse'].create({
            'name': 'Main Warehouse',
            'code': 'MW',
        })

        # Create a second warehouse for inter-warehouse tests
        cls.warehouse_b = cls.env['stocksense.warehouse'].create({
            'name': 'Secondary Warehouse',
            'code': 'SW',
        })

        # Get the auto-created stock locations
        cls.main_stock_loc = cls.warehouse.lot_stock_id
        cls.secondary_stock_loc = cls.warehouse_b.lot_stock_id

        # Get virtual locations
        cls.supplier_loc = cls.env.ref('stocksense.location_suppliers')
        cls.customer_loc = cls.env.ref('stocksense.location_customers')
        cls.adjustment_loc = cls.env.ref('stocksense.location_adjustment')

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
        """Helper to create and optionally validate a receipt operation."""
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
        """Helper to create and optionally validate a delivery operation."""
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
        """Helper to create an adjustment that adds stock (gain)."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'adjustment',
            'product_id': product.id,
            'destination_location_id': location.id,
            'quantity': quantity,
            'reason': 'Test adjustment - stock gain',
        })
        if validate:
            op.action_validate()
        return op

    def _create_adjustment_out(self, product, location, quantity, validate=True):
        """Helper to create an adjustment that removes stock (loss)."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'adjustment',
            'product_id': product.id,
            'source_location_id': location.id,
            'destination_location_id': location.id,
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
    # TEST 6: Adjustment changes stock correctly
    # ══════════════════════════════════════════════════════════════════

    def test_adjustment_in_increases_stock(self):
        """Stock-in adjustment should increase stock at the target location."""
        initial_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self._create_adjustment_in(self.product, self.main_stock_loc, 15)
        new_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(new_qty, initial_qty + 15,
                         "Adjustment in of 15 should increase stock by 15")

    def test_adjustment_out_decreases_stock(self):
        """Stock-out adjustment should decrease stock at the target location."""
        self._create_receipt(self.product, self.main_stock_loc, 50)
        initial_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self._create_adjustment_out(self.product, self.main_stock_loc, 3)
        new_qty = self._get_stock_qty(self.product, self.main_stock_loc)
        self.assertEqual(new_qty, initial_qty - 3,
                         "Adjustment out of 3 should decrease stock by 3")

    # ══════════════════════════════════════════════════════════════════
    # TEST 7: Every stock-changing action produces ledger movement
    # ══════════════════════════════════════════════════════════════════

    def test_receipt_creates_movement(self):
        """Receipt should create exactly one movement record."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        self.assertEqual(len(op.movement_ids), 1,
                         "Receipt should create exactly 1 movement")
        movement = op.movement_ids[0]
        self.assertEqual(movement.movement_type, 'receipt')
        self.assertEqual(movement.quantity, 100)
        self.assertEqual(movement.product_id, self.product)
        self.assertEqual(movement.destination_location_id, self.main_stock_loc)

    def test_delivery_creates_movement(self):
        """Delivery should create exactly one movement record."""
        self._create_receipt(self.product, self.main_stock_loc, 100)
        op = self._create_delivery(self.product, self.main_stock_loc, 30)
        self.assertEqual(len(op.movement_ids), 1,
                         "Delivery should create exactly 1 movement")
        movement = op.movement_ids[0]
        self.assertEqual(movement.movement_type, 'delivery')
        self.assertEqual(movement.quantity, 30)
        self.assertEqual(movement.source_location_id, self.main_stock_loc)

    def test_internal_transfer_creates_movement(self):
        """Internal transfer should create exactly one movement record."""
        self._create_receipt(self.product, self.main_stock_loc, 100)
        op = self._create_internal_transfer(
            self.product, self.main_stock_loc, self.secondary_stock_loc, 40
        )
        self.assertEqual(len(op.movement_ids), 1,
                         "Internal transfer should create exactly 1 movement")
        movement = op.movement_ids[0]
        self.assertEqual(movement.movement_type, 'internal')
        self.assertEqual(movement.source_location_id, self.main_stock_loc)
        self.assertEqual(movement.destination_location_id, self.secondary_stock_loc)
        self.assertEqual(movement.quantity, 40)

    def test_adjustment_creates_movement(self):
        """Adjustment should create exactly one movement record."""
        op = self._create_adjustment_in(self.product, self.main_stock_loc, 10)
        self.assertEqual(len(op.movement_ids), 1,
                         "Adjustment should create exactly 1 movement")
        movement = op.movement_ids[0]
        self.assertEqual(movement.movement_type, 'adjustment_in')
        self.assertEqual(movement.quantity, 10)

    def test_movement_has_audit_fields(self):
        """Every movement must have complete audit trail fields."""
        op = self._create_receipt(self.product, self.main_stock_loc, 50)
        movement = op.movement_ids[0]
        self.assertTrue(movement.date, "Movement must have a date")
        self.assertTrue(movement.user_id, "Movement must have a user")
        self.assertTrue(movement.operation_id, "Movement must reference its operation")
        self.assertEqual(movement.operation_id, op,
                         "Movement must reference the correct operation")

    # ══════════════════════════════════════════════════════════════════
    # TEST 8: Invalid quantities/locations are rejected
    # ══════════════════════════════════════════════════════════════════

    def test_reject_zero_quantity(self):
        """Operations with zero quantity should be rejected."""
        with self.assertRaises(ValidationError):
            self.env['stocksense.operation'].create({
                'operation_type': 'receipt',
                'product_id': self.product.id,
                'destination_location_id': self.main_stock_loc.id,
                'quantity': 0,
            })

    def test_reject_negative_quantity(self):
        """Operations with negative quantity should be rejected."""
        with self.assertRaises(ValidationError):
            self.env['stocksense.operation'].create({
                'operation_type': 'receipt',
                'product_id': self.product.id,
                'destination_location_id': self.main_stock_loc.id,
                'quantity': -10,
            })

    def test_reject_transfer_same_location(self):
        """Internal transfer to the same location should be rejected."""
        with self.assertRaises(ValidationError):
            self.env['stocksense.operation'].create({
                'operation_type': 'internal',
                'product_id': self.product.id,
                'source_location_id': self.main_stock_loc.id,
                'destination_location_id': self.main_stock_loc.id,
                'quantity': 10,
            })

    def test_reject_delivery_exceeds_stock(self):
        """Delivery exceeding available stock should be rejected."""
        self._create_receipt(self.product, self.main_stock_loc, 10)
        with self.assertRaises(UserError):
            self._create_delivery(self.product, self.main_stock_loc, 20)

    def test_reject_transfer_exceeds_stock(self):
        """Transfer exceeding available stock at source should be rejected."""
        self._create_receipt(self.product, self.main_stock_loc, 10)
        with self.assertRaises(UserError):
            self._create_internal_transfer(
                self.product, self.main_stock_loc, self.secondary_stock_loc, 50
            )

    def test_reject_receipt_to_virtual_location(self):
        """Receipt to a virtual (non-internal) location should be rejected."""
        with self.assertRaises(ValidationError):
            self.env['stocksense.operation'].create({
                'operation_type': 'receipt',
                'product_id': self.product.id,
                'destination_location_id': self.supplier_loc.id,
                'quantity': 10,
            })

    def test_reject_delivery_from_virtual_location(self):
        """Delivery from a virtual location should be rejected."""
        with self.assertRaises(ValidationError):
            self.env['stocksense.operation'].create({
                'operation_type': 'delivery',
                'product_id': self.product.id,
                'source_location_id': self.customer_loc.id,
                'quantity': 10,
            })

    def test_reject_duplicate_sku(self):
        """Products with duplicate SKU should be rejected."""
        with self.assertRaises(Exception):  # IntegrityError wrapped by Odoo
            self.env['stocksense.product'].create({
                'name': 'Another Widget',
                'sku': 'WGT-ALPHA-001',  # Same SKU as cls.product
                'category_id': self.category.id,
                'uom': 'unit',
            })

    # ══════════════════════════════════════════════════════════════════
    # TEST 9: Historical ledger records remain consistent (immutability)
    # ══════════════════════════════════════════════════════════════════

    def test_movement_immutable_cannot_modify(self):
        """Movement records should be immutable — write should fail."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        movement = op.movement_ids[0]
        with self.assertRaises(UserError):
            movement.write({'quantity': 200})

    def test_movement_immutable_cannot_delete(self):
        """Movement records should not be deletable."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        movement = op.movement_ids[0]
        with self.assertRaises(UserError):
            movement.unlink()

    def test_done_operation_cannot_cancel(self):
        """Completed operations should not be cancellable."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        self.assertEqual(op.state, 'done')
        with self.assertRaises(UserError):
            op.action_cancel()

    def test_done_operation_cannot_delete(self):
        """Completed operations should not be deletable."""
        op = self._create_receipt(self.product, self.main_stock_loc, 100)
        with self.assertRaises(UserError):
            op.unlink()

    # ══════════════════════════════════════════════════════════════════
    # Additional Integration Tests
    # ══════════════════════════════════════════════════════════════════

    def test_operation_lifecycle(self):
        """Test the full operation lifecycle: draft → confirmed → done."""
        op = self._create_receipt(self.product, self.main_stock_loc, 50, validate=False)
        self.assertEqual(op.state, 'draft')

        op.action_confirm()
        self.assertEqual(op.state, 'confirmed')

        op.action_validate()
        self.assertEqual(op.state, 'done')
        self.assertTrue(op.date_done, "Done operation must have a completion date")
        self.assertEqual(len(op.movement_ids), 1, "Validated operation must have movements")

    def test_cancel_and_reset_lifecycle(self):
        """Test cancelling and resetting an operation."""
        op = self._create_receipt(self.product, self.main_stock_loc, 50, validate=False)
        op.action_cancel()
        self.assertEqual(op.state, 'cancelled')
        self.assertEqual(len(op.movement_ids), 0, "Cancelled operation must not have movements")

        op.action_draft()
        self.assertEqual(op.state, 'draft')

    def test_operation_generates_sequence_reference(self):
        """Operations should get auto-generated reference numbers."""
        op = self._create_receipt(self.product, self.main_stock_loc, 10)
        self.assertNotEqual(op.name, 'New',
                            "Operation should have a generated reference, not 'New'")
        self.assertTrue(op.name.startswith('REC/'),
                        "Receipt reference should start with 'REC/'")

    def test_warehouse_auto_creates_locations(self):
        """Creating a warehouse should auto-create default locations."""
        wh = self.env['stocksense.warehouse'].create({
            'name': 'Test Auto Warehouse',
            'code': 'TAW',
        })
        self.assertTrue(wh.lot_stock_id, "Warehouse should have a default stock location")
        self.assertEqual(wh.lot_stock_id.name, 'Stock')
        # Should have at least 3 locations: Stock, Input, Output
        self.assertGreaterEqual(len(wh.location_ids), 3,
                                "Warehouse should have at least 3 auto-created locations")

    def test_stock_balance_consistency_with_ledger(self):
        """Stock balance should match the sum of movements."""
        # Perform several operations
        self._create_receipt(self.product, self.main_stock_loc, 100)
        self._create_receipt(self.product, self.main_stock_loc, 50)
        self._create_delivery(self.product, self.main_stock_loc, 30)
        self._create_internal_transfer(
            self.product, self.main_stock_loc, self.secondary_stock_loc, 20
        )

        # Check balance at main stock
        main_balance = self._get_stock_qty(self.product, self.main_stock_loc)

        # Calculate from movements
        movements = self.env['stocksense.movement'].search([
            ('product_id', '=', self.product.id),
        ])

        main_from_movements = 0.0
        for move in movements:
            if move.destination_location_id == self.main_stock_loc:
                main_from_movements += move.quantity
            if move.source_location_id == self.main_stock_loc:
                main_from_movements -= move.quantity

        self.assertEqual(
            main_balance, main_from_movements,
            "Stock balance (%.2f) must match movement sum (%.2f)"
            % (main_balance, main_from_movements)
        )

    def test_full_inventory_flow(self):
        """End-to-end test: receipt → transfer → delivery → adjustment."""
        # Step 1: Receive 200 units at main warehouse
        self._create_receipt(self.product, self.main_stock_loc, 200)
        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 200)

        # Step 2: Transfer 80 to secondary warehouse
        self._create_internal_transfer(
            self.product, self.main_stock_loc, self.secondary_stock_loc, 80
        )
        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 120)
        self.assertEqual(self._get_stock_qty(self.product, self.secondary_stock_loc), 80)
        self.assertEqual(self._get_total_company_stock(self.product), 200)

        # Step 3: Deliver 30 from main warehouse
        self._create_delivery(self.product, self.main_stock_loc, 30)
        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 90)
        self.assertEqual(self._get_total_company_stock(self.product), 170)

        # Step 4: Adjustment - found 5 extra units at secondary
        self._create_adjustment_in(self.product, self.secondary_stock_loc, 5)
        self.assertEqual(self._get_stock_qty(self.product, self.secondary_stock_loc), 85)
        self.assertEqual(self._get_total_company_stock(self.product), 175)

        # Step 5: Adjustment - 2 units damaged at main warehouse
        self._create_adjustment_out(self.product, self.main_stock_loc, 2)
        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 88)
        self.assertEqual(self._get_total_company_stock(self.product), 173)

        # Verify total movements created
        movements = self.env['stocksense.movement'].search([
            ('product_id', '=', self.product.id),
        ])
        self.assertEqual(len(movements), 5,
                         "Should have 5 movements from 5 operations")

    def test_reorder_rule_triggered(self):
        """Reorder rule should trigger when stock falls below minimum."""
        self._create_receipt(self.product, self.main_stock_loc, 100)

        rule = self.env['stocksense.reorder.rule'].create({
            'product_id': self.product.id,
            'location_id': self.main_stock_loc.id,
            'min_quantity': 20,
            'max_quantity': 100,
            'reorder_quantity': 80,
        })

        # Stock at 100, rule min at 20 — should not be triggered
        self.assertFalse(rule.is_triggered,
                         "Rule should not be triggered when stock (100) > min (20)")

        # Deliver 85, leaving 15
        self._create_delivery(self.product, self.main_stock_loc, 85)
        # Force recompute
        rule.invalidate_recordset(['current_stock', 'is_triggered'])
        self.assertTrue(rule.is_triggered,
                        "Rule should be triggered when stock (15) <= min (20)")

    def test_category_hierarchy(self):
        """Test hierarchical categories with computed complete names."""
        parent = self.env['stocksense.category'].create({'name': 'Electronics'})
        child = self.env['stocksense.category'].create({
            'name': 'Phones',
            'parent_id': parent.id,
        })
        grandchild = self.env['stocksense.category'].create({
            'name': 'Smartphones',
            'parent_id': child.id,
        })
        self.assertEqual(grandchild.complete_name, 'Electronics / Phones / Smartphones')

    def test_category_no_recursion(self):
        """Categories should not allow circular parent references."""
        cat_a = self.env['stocksense.category'].create({'name': 'A'})
        cat_b = self.env['stocksense.category'].create({'name': 'B', 'parent_id': cat_a.id})
        with self.assertRaises(ValidationError):
            cat_a.parent_id = cat_b.id

    def test_multi_product_independence(self):
        """Stock operations on one product should not affect another."""
        self._create_receipt(self.product, self.main_stock_loc, 100)
        self._create_receipt(self.product_b, self.main_stock_loc, 50)

        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 100)
        self.assertEqual(self._get_stock_qty(self.product_b, self.main_stock_loc), 50)

        self._create_delivery(self.product, self.main_stock_loc, 20)
        self.assertEqual(self._get_stock_qty(self.product, self.main_stock_loc), 80)
        self.assertEqual(self._get_stock_qty(self.product_b, self.main_stock_loc), 50,
                         "Delivery of product A should not affect product B stock")
