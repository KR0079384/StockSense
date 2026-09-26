# -*- coding: utf-8 -*-
"""Inventory Dashboard (TransientModel).

Phase 1 - Dashboard Foundation. Read-only dashboard over the
existing source-of-truth models. Does NOT persist KPI data and does
NOT alter ledger / state-machine behaviour.
"""
from odoo import models, fields, api


PENDING_STATES = ('draft', 'confirmed')


class StockSenseDashboard(models.TransientModel):
    _name = 'stocksense.dashboard'
    _description = 'Inventory Dashboard'

    warehouse_id = fields.Many2one(
        'stocksense.warehouse',
        string='Warehouse',
    )
    location_id = fields.Many2one(
        'stocksense.location',
        string='Location',
        domain=[('location_type', '=', 'internal')],
    )
    category_id = fields.Many2one(
        'stocksense.category',
        string='Product Category',
    )
    filter_operation_type = fields.Selection(
        selection=[
            ('all', 'All Types'),
            ('receipt', 'Receipt'),
            ('delivery', 'Delivery'),
            ('internal', 'Internal Transfer'),
            ('adjustment', 'Adjustment'),
        ],
        string='Operation Type',
        default='all',
        required=True,
    )
    filter_state = fields.Selection(
        selection=[
            ('all', 'All Statuses'),
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='all',
        required=True,
    )

    total_products_in_stock = fields.Integer(
        string='Total Products in Stock',
        compute='_compute_kpis',
        readonly=True,
    )
    low_stock_count = fields.Integer(
        string='Low Stock',
        compute='_compute_kpis',
        readonly=True,
    )
    out_of_stock_count = fields.Integer(
        string='Out of Stock',
        compute='_compute_kpis',
        readonly=True,
    )
    reorder_needed_count = fields.Integer(
        string='Reorder Needed',
        compute='_compute_kpis',
        readonly=True,
    )
    pending_receipts_count = fields.Integer(
        string='Pending Receipts',
        compute='_compute_kpis',
        readonly=True,
    )
    pending_deliveries_count = fields.Integer(
        string='Pending Deliveries',
        compute='_compute_kpis',
        readonly=True,
    )
    internal_transfers_scheduled_count = fields.Integer(
        string='Internal Transfers Scheduled',
        compute='_compute_kpis',
        readonly=True,
    )

    def _get_category_ids(self):
        """Return [category + children] ids for hierarchical filtering."""
        self.ensure_one()
        if not self.category_id:
            return []
        return self.env['stocksense.category'].search(
            [('id', 'child_of', self.category_id.id)]
        ).ids

    def _stock_domain(self):
        """Base domain on stocksense.stock using stored fields only."""
        self.ensure_one()
        domain = [('location_id.location_type', '=', 'internal')]
        if self.warehouse_id:
            domain.append(('warehouse_id', '=', self.warehouse_id.id))
        if self.location_id:
            domain.append(('location_id', '=', self.location_id.id))
        category_ids = self._get_category_ids()
        if category_ids:
            domain.append(('product_category_id', 'in', category_ids))
        return domain

    def _product_domain(self):
        self.ensure_one()
        category_ids = self._get_category_ids()
        if category_ids:
            return [('category_id', 'in', category_ids)]
        return []

    def _operation_domain(self, operation_type):
        """Domain for a pending-type KPI using source/destination locations."""
        self.ensure_one()
        domain = [
            ('operation_type', '=', operation_type),
            ('state', 'in', list(PENDING_STATES)),
        ]
        if self.warehouse_id:
            wid = self.warehouse_id.id
            if operation_type == 'receipt':
                domain.append(('destination_location_id.warehouse_id', '=', wid))
            elif operation_type == 'delivery':
                domain.append(('source_location_id.warehouse_id', '=', wid))
            else:
                domain += [
                    '|',
                    ('source_location_id.warehouse_id', '=', wid),
                    ('destination_location_id.warehouse_id', '=', wid),
                ]
        if self.location_id:
            lid = self.location_id.id
            if operation_type == 'receipt':
                domain.append(('destination_location_id', '=', lid))
            elif operation_type == 'delivery':
                domain.append(('source_location_id', '=', lid))
            else:
                domain += [
                    '|',
                    ('source_location_id', '=', lid),
                    ('destination_location_id', '=', lid),
                ]
        category_ids = self._get_category_ids()
        if category_ids:
            domain.append(('line_ids.product_id.category_id', 'in', category_ids))
        return domain

    def _reorder_rule_domain(self):
        self.ensure_one()
        domain = [('active', '=', True)]
        if self.warehouse_id:
            domain.append(('warehouse_id', '=', self.warehouse_id.id))
        if self.location_id:
            domain.append(('location_id', '=', self.location_id.id))
        category_ids = self._get_category_ids()
        if category_ids:
            domain.append(('product_id.category_id', 'in', category_ids))
        return domain

    @api.depends('warehouse_id', 'location_id', 'category_id')
    def _compute_kpis(self):
        for dashboard in self:
            dashboard.total_products_in_stock = dashboard._count_products_in_stock()
            dashboard.low_stock_count = dashboard._count_low_stock()
            dashboard.out_of_stock_count = dashboard._count_out_of_stock()
            dashboard.reorder_needed_count = dashboard._count_reorder_needed()
            dashboard.pending_receipts_count = dashboard._count_pending('receipt')
            dashboard.pending_deliveries_count = dashboard._count_pending('delivery')
            dashboard.internal_transfers_scheduled_count = dashboard._count_pending('internal')

    def _aggregated_qty_by_product(self):
        """Return {product_id: scoped_qty} for stock lines in scope."""
        self.ensure_one()
        totals = {}
        stocks = self.env['stocksense.stock'].search(self._stock_domain())
        for stock in stocks:
            totals[stock.product_id.id] = totals.get(stock.product_id.id, 0.0) + stock.quantity
        return totals

    def _count_products_in_stock(self):
        self.ensure_one()
        totals = self._aggregated_qty_by_product()
        return sum(1 for qty in totals.values() if qty > 0)

    def _count_low_stock(self):
        """Reuse stocksense.stock.is_below_reorder semantics."""
        self.ensure_one()
        domain = self._stock_domain() + [('is_below_reorder', '=', True)]
        return self.env['stocksense.stock'].search_count(domain)

    def _count_out_of_stock(self):
        """Distinct products with scoped aggregate stock <= 0."""
        self.ensure_one()
        totals = self._aggregated_qty_by_product()
        scoped = [pid for pid, qty in totals.items() if qty <= 0]
        if not self.warehouse_id and not self.location_id:
            all_ids = self.env['stocksense.product'].search(self._product_domain()).ids
            missing = [pid for pid in all_ids if pid not in totals]
            return len(scoped) + len(missing)
        return len(scoped)

    def _count_reorder_needed(self):
        """Reuse stocksense.reorder.rule.is_triggered semantics."""
        self.ensure_one()
        domain = self._reorder_rule_domain() + [('is_triggered', '=', True)]
        return self.env['stocksense.reorder.rule'].search_count(domain)

    def _count_pending(self, operation_type):
        self.ensure_one()
        return self.env['stocksense.operation'].search_count(
            self._operation_domain(operation_type)
        )

    def get_dashboard_data(self):
        self.ensure_one()
        return {
            'total_products_in_stock': self.total_products_in_stock,
            'low_stock_count': self.low_stock_count,
            'out_of_stock_count': self.out_of_stock_count,
            'reorder_needed_count': self.reorder_needed_count,
            'pending_receipts_count': self.pending_receipts_count,
            'pending_deliveries_count': self.pending_deliveries_count,
            'internal_transfers_scheduled_count': self.internal_transfers_scheduled_count,
            'domains': {
                'low_stock': self._stock_domain() + [('is_below_reorder', '=', True)],
                'reorder_needed': self._reorder_rule_domain() + [('is_triggered', '=', True)],
                'pending_receipts': self._operation_domain('receipt'),
                'pending_deliveries': self._operation_domain('delivery'),
                'pending_internal': self._operation_domain('internal'),
            },
        }

    def _action_for(self, name, res_model, domain):
        return {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': res_model,
            'view_mode': 'tree,form',
            'domain': domain,
            'target': 'current',
        }

    def action_view_products_in_stock(self):
        self.ensure_one()
        return self._action_for(
            'Products in Stock', 'stocksense.stock', self._stock_domain()
        )

    def action_view_low_stock(self):
        self.ensure_one()
        return self._action_for(
            'Low Stock',
            'stocksense.stock',
            self._stock_domain() + [('is_below_reorder', '=', True)],
        )

    def action_view_out_of_stock(self):
        self.ensure_one()
        totals = self._aggregated_qty_by_product()
        product_ids = [pid for pid, qty in totals.items() if qty <= 0]
        if not self.warehouse_id and not self.location_id:
            all_ids = self.env['stocksense.product'].search(self._product_domain()).ids
            product_ids += [pid for pid in all_ids if pid not in totals]
        return self._action_for(
            'Out of Stock', 'stocksense.product', [('id', 'in', product_ids)]
        )

    def action_view_reorder_needed(self):
        self.ensure_one()
        return self._action_for(
            'Reorder Needed',
            'stocksense.reorder.rule',
            self._reorder_rule_domain() + [('is_triggered', '=', True)],
        )

    def action_view_pending_receipts(self):
        self.ensure_one()
        return self._action_for(
            'Pending Receipts', 'stocksense.operation', self._operation_domain('receipt')
        )

    def action_view_pending_deliveries(self):
        self.ensure_one()
        return self._action_for(
            'Pending Deliveries', 'stocksense.operation', self._operation_domain('delivery')
        )

    def action_view_internal_transfers(self):
        self.ensure_one()
        return self._action_for(
            'Internal Transfers Scheduled',
            'stocksense.operation',
            self._operation_domain('internal'),
        )



