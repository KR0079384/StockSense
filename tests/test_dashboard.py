# -*- coding: utf-8 -*-
"""StockSense Dashboard Tests (Phase 1 foundation)."""
from odoo.tests.common import TransactionCase


class TestStockSenseDashboard(TransactionCase):
    """Tests for stocksense.dashboard KPIs and filters."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.category = cls.env['stocksense.category'].create({
            'name': 'Dashboard Category',
        })
        cls.category_other = cls.env['stocksense.category'].create({
            'name': 'Dashboard Other Category',
        })
        cls.child_category = cls.env['stocksense.category'].create({
            'name': 'Dashboard Child Category',
            'parent_id': cls.category.id,
        })
        cls.product = cls.env['stocksense.product'].create({
            'name': 'Dashboard Alpha',
            'sku': 'DSH-ALPHA-001',
            'category_id': cls.category.id,
            'uom': 'unit',
        })
        cls.product_b = cls.env['stocksense.product'].create({
            'name': 'Dashboard Beta',
            'sku': 'DSH-BETA-001',
            'category_id': cls.category_other.id,
            'uom': 'unit',
        })
        cls.product_child = cls.env['stocksense.product'].create({
            'name': 'Dashboard Gamma',
            'sku': 'DSH-GAMMA-001',
            'category_id': cls.child_category.id,
            'uom': 'unit',
        })
        cls.warehouse = cls.env['stocksense.warehouse'].create({
            'name': 'Dashboard Warehouse',
            'code': 'DWH',
        })
        cls.warehouse_b = cls.env['stocksense.warehouse'].create({
            'name': 'Dashboard Warehouse B',
            'code': 'DWB',
        })
        cls.main_stock_loc = cls.warehouse.lot_stock_id
        cls.secondary_stock_loc = cls.warehouse_b.lot_stock_id

    def _dashboard(self, **vals):
        return self.env['stocksense.dashboard'].create(vals)

    def _receipt(self, product, location, qty, validate=True):
        op = self.env['stocksense.operation'].create({
            'operation_type': 'receipt',
            'product_id': product.id,
            'destination_location_id': location.id,
            'quantity': qty,
        })
        if validate:
            op.action_validate()
        return op

    def test_dashboard_model_access(self):
        dash = self._dashboard()
        self.assertEqual(dash.total_products_in_stock, 0)
        self.assertEqual(dash.low_stock_count, 0)
        self.assertEqual(dash.out_of_stock_count, 3)
        self.assertEqual(dash.reorder_needed_count, 0)
        self.assertEqual(dash.pending_receipts_count, 0)
        self.assertEqual(dash.pending_deliveries_count, 0)
        self.assertEqual(dash.internal_transfers_scheduled_count, 0)
        data = dash.get_dashboard_data()
        self.assertIn('domains', data)
        self.assertIn('pending_receipts', data['domains'])

    def test_total_products_in_stock(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self._receipt(self.product_b, self.main_stock_loc, 5)
        dash = self._dashboard()
        self.assertEqual(dash.total_products_in_stock, 2)
        self.assertEqual(dash.get_dashboard_data()['total_products_in_stock'], 2)

    def test_low_stock_kpi(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self.assertEqual(self._dashboard().low_stock_count, 0)
        self.env['stocksense.reorder.rule'].create({
            'product_id': self.product.id,
            'location_id': self.main_stock_loc.id,
            'min_quantity': 20.0,
            'reorder_quantity': 50.0,
        })
        dash = self._dashboard()
        self.assertEqual(dash.low_stock_count, 1)

    def test_out_of_stock_kpi(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        dash = self._dashboard()
        self.assertEqual(dash.out_of_stock_count, 2)
        action = dash.action_view_out_of_stock()
        self.assertEqual(action['res_model'], 'stocksense.product')
        self.assertIn(self.product_b.id, action['domain'][0][2])
        self.assertIn(self.product_child.id, action['domain'][0][2])
        self.assertNotIn(self.product.id, action['domain'][0][2])

    def test_pending_receipt_count(self):
        self._receipt(self.product, self.main_stock_loc, 10, validate=False)
        done_op = self._receipt(self.product, self.main_stock_loc, 10, validate=True)
        self.assertEqual(done_op.state, 'done')
        self.assertEqual(self._dashboard().pending_receipts_count, 1)

    def test_pending_delivery_count(self):
        self._receipt(self.product, self.main_stock_loc, 50)
        self.env['stocksense.operation'].create({
            'operation_type': 'delivery',
            'product_id': self.product.id,
            'source_location_id': self.main_stock_loc.id,
            'quantity': 5,
        })
        self.assertEqual(self._dashboard().pending_deliveries_count, 1)

    def test_internal_transfer_count(self):
        self._receipt(self.product, self.main_stock_loc, 50)
        self.env['stocksense.operation'].create({
            'operation_type': 'internal',
            'product_id': self.product.id,
            'source_location_id': self.main_stock_loc.id,
            'destination_location_id': self.secondary_stock_loc.id,
            'quantity': 5,
        })
        self.assertEqual(self._dashboard().internal_transfers_scheduled_count, 1)

    def test_warehouse_filtering(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self._receipt(self.product_b, self.secondary_stock_loc, 7)
        self.assertEqual(self._dashboard().total_products_in_stock, 2)
        dash_a = self._dashboard(warehouse_id=self.warehouse.id)
        self.assertEqual(dash_a.total_products_in_stock, 1)
        dash_b = self._dashboard(warehouse_id=self.warehouse_b.id)
        self.assertEqual(dash_b.total_products_in_stock, 1)

    def test_location_filtering(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        dash = self._dashboard(location_id=self.main_stock_loc.id)
        self.assertEqual(dash.total_products_in_stock, 1)
        dash_empty = self._dashboard(location_id=self.secondary_stock_loc.id)
        self.assertEqual(dash_empty.total_products_in_stock, 0)

    def test_category_filtering(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self._receipt(self.product_b, self.main_stock_loc, 10)
        self._receipt(self.product_child, self.main_stock_loc, 10)
        self.assertEqual(self._dashboard().total_products_in_stock, 3)
        dash = self._dashboard(category_id=self.category.id)
        self.assertEqual(dash.total_products_in_stock, 2)
        dash_other = self._dashboard(category_id=self.category_other.id)
        self.assertEqual(dash_other.total_products_in_stock, 1)

    # ── Phase 2: analytics + recent activity ──

    def test_stock_grouped_by_warehouse(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self._receipt(self.product_b, self.secondary_stock_loc, 7)
        groups = self._dashboard().get_stock_by_warehouse()
        by_wh = {g['warehouse_id'][0]: g['quantity'] for g in groups}
        self.assertEqual(by_wh[self.warehouse.id], 10)
        self.assertEqual(by_wh[self.warehouse_b.id], 7)

    def test_stock_grouped_by_location(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self._receipt(self.product_b, self.secondary_stock_loc, 7)
        groups = self._dashboard().get_stock_by_location()
        by_loc = {g['location_id'][0]: g['quantity'] for g in groups}
        self.assertEqual(by_loc[self.main_stock_loc.id], 10)
        self.assertEqual(by_loc[self.secondary_stock_loc.id], 7)

    def test_stock_grouped_by_category(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self._receipt(self.product_b, self.main_stock_loc, 4)
        groups = self._dashboard().get_stock_by_category()
        by_cat = {g['product_category_id'][0]: g['quantity'] for g in groups}
        self.assertEqual(by_cat[self.category.id], 10)
        self.assertEqual(by_cat[self.category_other.id], 4)

    def test_recent_movements_ordering_limit(self):
        for _i in range(12):
            self._receipt(self.product, self.main_stock_loc, 1)
        recents = self._dashboard().get_recent_movements()
        self.assertEqual(len(recents), 10)
        dates = recents.mapped('date')
        self.assertEqual(list(dates), sorted(dates, reverse=True))
        action = self._dashboard().action_view_recent_movements()
        self.assertEqual(action['res_model'], 'stocksense.movement')
        self.assertEqual(action['limit'], 10)

    def test_recent_receipts(self):
        op = self._receipt(self.product, self.main_stock_loc, 5)
        recents = self._dashboard().get_recent_operations('receipt')
        self.assertIn(op.id, recents.ids)
        action = self._dashboard().action_view_recent_receipts()
        self.assertEqual(action['res_model'], 'stocksense.operation')

    def test_recent_deliveries(self):
        self._receipt(self.product, self.main_stock_loc, 50)
        op = self.env['stocksense.operation'].create({
            'operation_type': 'delivery',
            'product_id': self.product.id,
            'source_location_id': self.main_stock_loc.id,
            'quantity': 5,
        })
        op.action_validate()
        recents = self._dashboard().get_recent_operations('delivery')
        self.assertIn(op.id, recents.ids)
        action = self._dashboard().action_view_recent_deliveries()
        self.assertEqual(action['res_model'], 'stocksense.operation')

    def test_recent_internal_transfers(self):
        self._receipt(self.product, self.main_stock_loc, 50)
        op = self.env['stocksense.operation'].create({
            'operation_type': 'internal',
            'product_id': self.product.id,
            'source_location_id': self.main_stock_loc.id,
            'destination_location_id': self.secondary_stock_loc.id,
            'quantity': 5,
        })
        op.action_validate()
        recents = self._dashboard().get_recent_operations('internal')
        self.assertIn(op.id, recents.ids)
        action = self._dashboard().action_view_recent_transfers()
        self.assertEqual(action['res_model'], 'stocksense.operation')

    def test_low_stock_records(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        self.env['stocksense.reorder.rule'].create({
            'product_id': self.product.id,
            'location_id': self.main_stock_loc.id,
            'min_quantity': 20.0,
            'reorder_quantity': 50.0,
        })
        records = self._dashboard().get_low_stock_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records.product_id, self.product)
        self.assertEqual(records.reorder_min_qty, 20.0)
        self.assertTrue(records.is_below_reorder)

    def test_out_of_stock_product_behavior(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        products = self._dashboard().get_out_of_stock_products()
        self.assertEqual(set(products.ids), {self.product_b.id, self.product_child.id})
        action = self._dashboard().action_view_out_of_stock()
        self.assertEqual(action['res_model'], 'stocksense.product')

    def test_reorder_needed_records(self):
        self._receipt(self.product, self.main_stock_loc, 10)
        rule = self.env['stocksense.reorder.rule'].create({
            'product_id': self.product.id,
            'location_id': self.main_stock_loc.id,
            'min_quantity': 20.0,
            'max_quantity': 100.0,
            'reorder_quantity': 50.0,
        })
        records = self._dashboard().get_reorder_needed_records()
        self.assertIn(rule.id, records.ids)
        self.assertTrue(records[0].is_triggered)
        self.assertEqual(records[0].current_stock, 10.0)

