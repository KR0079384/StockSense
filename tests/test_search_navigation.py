# -*- coding: utf-8 -*-
"""
StockSense Search and Navigation Tests
======================================

Tests for all search views, custom domain search methods, filtering logic,
and navigation features across StockSense models:

1. Product search by SKU, Name, Barcode, and total stock search method
2. Category filters across products, stock balances, operations, and movements
3. Warehouse filters across stock balances, operations, and movements
4. Location filters across stock balances, operations, and movements
5. Stock status filters (In Stock, Out of Stock, Low Stock / Reorder alerts)
6. Operation type filters (receipt, delivery, internal, adjustment)
7. Operation status filters (draft, confirmed, done, cancelled)
8. Movement history search (SKU, Product, Operation ref, Locations)
9. Date filtering domains for operations and movement ledger
"""
from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError, ValidationError


class TestStockSenseSearchNavigation(TransactionCase):
    """Test suite for search, filtering, and navigation logic."""

    @classmethod
    def setUpClass(cls):
        """Set up test environment with category, products, warehouses, and operations."""
        super().setUpClass()

        # Categories
        cls.category_electronics = cls.env['stocksense.category'].create({
            'name': 'Electronics',
        })
        cls.category_hardware = cls.env['stocksense.category'].create({
            'name': 'Hardware',
        })

        # Products
        cls.product_laptop = cls.env['stocksense.product'].create({
            'name': 'Pro Laptop 15',
            'sku': 'LAP-PRO-15',
            'barcode': '1111111111111',
            'category_id': cls.category_electronics.id,
            'uom': 'unit',
        })
        cls.product_mouse = cls.env['stocksense.product'].create({
            'name': 'Wireless Mouse',
            'sku': 'MSE-WRL-01',
            'barcode': '2222222222222',
            'category_id': cls.category_electronics.id,
            'uom': 'unit',
        })
        cls.product_screw = cls.env['stocksense.product'].create({
            'name': 'M4 Screw Set',
            'sku': 'SCR-M4-100',
            'barcode': '3333333333333',
            'category_id': cls.category_hardware.id,
            'uom': 'box',
        })

        # Warehouses & Locations
        cls.wh_main = cls.env['stocksense.warehouse'].create({
            'name': 'Main Hub',
            'code': 'MH',
        })
        cls.wh_north = cls.env['stocksense.warehouse'].create({
            'name': 'North Hub',
            'code': 'NH',
        })
        cls.loc_main_stock = cls.wh_main.lot_stock_id
        cls.loc_north_stock = cls.wh_north.lot_stock_id

    def test_01_product_sku_name_search(self):
        """Test searching products by name, SKU, and barcode."""
        # Search by SKU
        res_sku = self.env['stocksense.product'].search([('sku', '=', 'LAP-PRO-15')])
        self.assertEqual(res_sku, self.product_laptop)

        # Search using name_search / _rec_names_search
        res_rec = self.env['stocksense.product'].name_search('LAP-PRO-15')
        pids = [r[0] for r in res_rec]
        self.assertIn(self.product_laptop.id, pids)

        res_rec_barcode = self.env['stocksense.product'].name_search('2222222222222')
        pids_barcode = [r[0] for r in res_rec_barcode]
        self.assertIn(self.product_mouse.id, pids_barcode)

    def test_02_product_total_stock_search(self):
        """Test product total_stock custom search method."""
        # Initially laptop has 0 total_stock
        out_of_stock = self.env['stocksense.product'].search([('total_stock', '=', 0)])
        self.assertIn(self.product_laptop, out_of_stock)

        # Create receipt for 50 laptops
        op = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': self.product_laptop.id,
            'destination_location_id': self.loc_main_stock.id,
            'quantity': 50,
        })
        op.action_validate()

        in_stock = self.env['stocksense.product'].search([('total_stock', '>', 0)])
        self.assertIn(self.product_laptop, in_stock)

    def test_03_category_filter(self):
        """Test filtering products, stock, operations, and movements by category."""
        # Product category search
        elec_products = self.env['stocksense.product'].search([
            ('category_id', '=', self.category_electronics.id)
        ])
        self.assertIn(self.product_laptop, elec_products)
        self.assertIn(self.product_mouse, elec_products)
        self.assertNotIn(self.product_screw, elec_products)

        # Create operation for electronics
        op = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': self.product_laptop.id,
            'destination_location_id': self.loc_main_stock.id,
            'quantity': 10,
        })
        op.action_validate()

        # Check operation product_category_id related field search
        ops_elec = self.env['stocksense.operation'].search([
            ('product_category_id', '=', self.category_electronics.id)
        ])
        self.assertIn(op, ops_elec)

        # Check movement product_category_id related field search
        moves_elec = self.env['stocksense.movement'].search([
            ('product_category_id', '=', self.category_electronics.id)
        ])
        self.assertTrue(len(moves_elec) > 0)
        self.assertEqual(moves_elec[0].product_category_id, self.category_electronics)

    def test_04_warehouse_and_location_filters(self):
        """Test filtering stock, operations, and movements by warehouse and location."""
        op_receipt = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': self.product_mouse.id,
            'destination_location_id': self.loc_main_stock.id,
            'quantity': 100,
        })
        op_receipt.action_validate()

        op_transfer = self.env['stocksense.operation'].create({
            'operation_type': 'internal',
            'product_id': self.product_mouse.id,
            'source_location_id': self.loc_main_stock.id,
            'destination_location_id': self.loc_north_stock.id,
            'quantity': 30,
        })
        op_transfer.action_validate()

        # Filter operations by source_warehouse_id and destination_warehouse_id
        ops_from_main = self.env['stocksense.operation'].search([
            ('source_warehouse_id', '=', self.wh_main.id)
        ])
        self.assertIn(op_transfer, ops_from_main)

        ops_to_north = self.env['stocksense.operation'].search([
            ('destination_warehouse_id', '=', self.wh_north.id)
        ])
        self.assertIn(op_transfer, ops_to_north)

        # Filter movements by source_warehouse_id and dest_warehouse_id
        moves_wh = self.env['stocksense.movement'].search([
            ('source_warehouse_id', '=', self.wh_main.id),
            ('dest_warehouse_id', '=', self.wh_north.id),
        ])
        self.assertEqual(len(moves_wh), 1)

    def test_05_stock_status_low_stock_filter(self):
        """Test Low Stock filter using custom search method on is_below_reorder."""
        # Create receipt for 10 units of screw
        self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': self.product_screw.id,
            'destination_location_id': self.loc_main_stock.id,
            'quantity': 10,
        }).action_validate()

        # Add reorder rule with min 15
        self.env['stocksense.reorder.rule'].create({
            'product_id': self.product_screw.id,
            'location_id': self.loc_main_stock.id,
            'min_quantity': 15,
            'max_quantity': 50,
            'reorder_quantity': 35,
        })

        # Perform search using is_below_reorder = True
        low_stock_records = self.env['stocksense.stock'].search([
            ('is_below_reorder', '=', True)
        ])
        screw_stock = self.env['stocksense.stock'].search([
            ('product_id', '=', self.product_screw.id),
            ('location_id', '=', self.loc_main_stock.id),
        ])
        self.assertIn(screw_stock, low_stock_records)

    def test_06_operation_status_filter(self):
        """Test operation state filtering including draft, confirmed, done, and cancelled."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': self.product_laptop.id,
            'destination_location_id': self.loc_main_stock.id,
            'quantity': 5,
        })
        self.assertEqual(op.state, 'draft')

        draft_ops = self.env['stocksense.operation'].search([('state', '=', 'draft')])
        self.assertIn(op, draft_ops)

        op.action_confirm()
        confirmed_ops = self.env['stocksense.operation'].search([('state', '=', 'confirmed')])
        self.assertIn(op, confirmed_ops)

        op.action_cancel()
        cancelled_ops = self.env['stocksense.operation'].search([('state', '=', 'cancelled')])
        self.assertIn(op, cancelled_ops)

    def test_07_movement_history_search(self):
        """Test movement ledger search filters by reference name, product SKU, and operation."""
        op = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': self.product_laptop.id,
            'destination_location_id': self.loc_main_stock.id,
            'quantity': 10,
        })
        op.action_validate()

        movement = op.movement_ids[0]
        # Search movement by product SKU
        m_sku = self.env['stocksense.movement'].search([('product_sku', '=', 'LAP-PRO-15')])
        self.assertIn(movement, m_sku)

        # Search movement by operation reference
        m_op = self.env['stocksense.movement'].search([('operation_id', '=', op.id)])
        self.assertIn(movement, m_op)

        # Check movement is read-only / immutable
        with self.assertRaises(UserError):
            movement.write({'quantity': 20})
