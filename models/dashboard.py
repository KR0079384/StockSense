# -*- coding: utf-8 -*-
"""Inventory Dashboard (TransientModel).

Phase 1 - Dashboard Foundation + Phase 2 Analytics + Phase 3
finalization. Read-only dashboard over the existing source-of-truth
models. Does NOT persist KPI data and does NOT alter ledger /
state-machine behaviour.
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
            # Single scoped stock fetch reused for both distinct-product
            # KPIs (avoids 2x identical search per record).
            totals = dashboard._aggregated_qty_by_product()
            dashboard.total_products_in_stock = sum(1 for qty in totals.values() if qty > 0)
            dashboard.out_of_stock_count = dashboard._count_out_of_stock(totals)
            dashboard.low_stock_count = dashboard._count_low_stock()
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

    def _out_of_stock_product_ids(self, totals=None):
        """Product-level out-of-stock ids (aggregate <= 0, no double count)."""
        self.ensure_one()
        if totals is None:
            totals = self._aggregated_qty_by_product()
        product_ids = [pid for pid, qty in totals.items() if qty <= 0]
        if not self.warehouse_id and not self.location_id:
            all_ids = self.env['stocksense.product'].search(self._product_domain()).ids
            product_ids += [pid for pid in all_ids if pid not in totals]
        return product_ids

    def _count_out_of_stock(self, totals=None):
        self.ensure_one()
        return len(self._out_of_stock_product_ids(totals=totals))

    def _count_low_stock(self):
        """Reuse stocksense.stock.is_below_reorder semantics."""
        self.ensure_one()
        domain = self._stock_domain() + [('is_below_reorder', '=', True)]
        return self.env['stocksense.stock'].search_count(domain)

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
        product_ids = self._out_of_stock_product_ids()
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

    # PHASE 2 - Analytics (stored fields, read-only).
    # Stock rows are exact product@location; no hierarchy rollup.
    RECENT_LIMIT = 10

    def _recent_movement_domain(self):
        self.ensure_one()
        domain = []
        category_ids = self._get_category_ids()
        if category_ids:
            domain.append(('product_category_id', 'in', category_ids))
        if self.warehouse_id:
            wid = self.warehouse_id.id
            domain += [
                '|',
                ('source_location_id.warehouse_id', '=', wid),
                ('destination_location_id.warehouse_id', '=', wid),
            ]
        if self.location_id:
            lid = self.location_id.id
            domain += [
                '|',
                ('source_location_id', '=', lid),
                ('destination_location_id', '=', lid),
            ]
        return domain

    def _recent_operation_domain(self, operation_type):
        """Recent ops of a type, all states unless filter_state narrows."""
        self.ensure_one()
        domain = [('operation_type', '=', operation_type)]
        if self.filter_state and self.filter_state != 'all':
            domain.append(('state', '=', self.filter_state))
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

    def get_stock_by_warehouse(self):
        """SUM(quantity) grouped by warehouse (internal only)."""
        self.ensure_one()
        return self.env['stocksense.stock'].read_group(
            self._stock_domain(), ['warehouse_id', 'quantity'], ['warehouse_id']
        )

    def get_stock_by_location(self):
        """SUM(quantity) grouped by exact location (no rollup)."""
        self.ensure_one()
        return self.env['stocksense.stock'].read_group(
            self._stock_domain(), ['location_id', 'quantity'], ['location_id']
        )

    def get_stock_by_category(self):
        """SUM(quantity) grouped by stored product_category_id."""
        self.ensure_one()
        return self.env['stocksense.stock'].read_group(
            self._stock_domain(),
            ['product_category_id', 'quantity'],
            ['product_category_id'],
        )

    def get_recent_movements(self, limit=None):
        self.ensure_one()
        return self.env['stocksense.movement'].search(
            self._recent_movement_domain(),
            order='date desc, id desc',
            limit=limit or self.RECENT_LIMIT,
        )

    def get_recent_operations(self, operation_type, limit=None):
        self.ensure_one()
        return self.env['stocksense.operation'].search(
            self._recent_operation_domain(operation_type),
            order='date desc, id desc',
            limit=limit or self.RECENT_LIMIT,
        )

    def get_low_stock_records(self, limit=None):
        self.ensure_one()
        domain = self._stock_domain() + [('is_below_reorder', '=', True)]
        if limit:
            return self.env['stocksense.stock'].search(domain, limit=limit)
        return self.env['stocksense.stock'].search(domain)

    def get_out_of_stock_products(self):
        self.ensure_one()
        product_ids = self._out_of_stock_product_ids()
        if not product_ids:
            return self.env['stocksense.product'].browse([])
        return self.env['stocksense.product'].search([('id', 'in', product_ids)])

    def get_reorder_needed_records(self):
        self.ensure_one()
        domain = self._reorder_rule_domain() + [('is_triggered', '=', True)]
        return self.env['stocksense.reorder.rule'].search(domain)

    def action_view_internal_transfers(self):
        self.ensure_one()
        return self._action_for(
            'Internal Transfers Scheduled',
            'stocksense.operation',
            self._operation_domain('internal'),
        )

    def _limited_action(self, name, res_model, domain):
        action = self._action_for(name, res_model, domain)
        action['limit'] = self.RECENT_LIMIT
        return action

    def action_open_stock_by_warehouse(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock by Warehouse (SUM of internal stock)',
            'res_model': 'stocksense.stock',
            'view_mode': 'graph,pivot,tree,form',
            'views': [
                (self.env.ref('stocksense.view_stock_warehouse_graph').id, 'graph'),
                (self.env.ref('stocksense.view_stock_warehouse_pivot').id, 'pivot'),
                (False, 'tree'),
                (False, 'form'),
            ],
            'domain': self._stock_domain(),
            'context': {'group_by': ['warehouse_id']},
            'target': 'current',
        }

    def action_open_stock_by_location(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock by Location (exact locations, no rollup)',
            'res_model': 'stocksense.stock',
            'view_mode': 'graph,pivot,tree,form',
            'views': [
                (self.env.ref('stocksense.view_stock_location_graph').id, 'graph'),
                (self.env.ref('stocksense.view_stock_location_pivot').id, 'pivot'),
                (False, 'tree'),
                (False, 'form'),
            ],
            'domain': self._stock_domain(),
            'context': {'group_by': ['location_id']},
            'target': 'current',
        }

    def action_open_stock_by_category(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Stock by Category (stored qty; mixed UoMs not comparable)',
            'res_model': 'stocksense.stock',
            'view_mode': 'graph,pivot,tree,form',
            'views': [
                (self.env.ref('stocksense.view_stock_category_graph').id, 'graph'),
                (self.env.ref('stocksense.view_stock_category_pivot').id, 'pivot'),
                (False, 'tree'),
                (False, 'form'),
            ],
            'domain': self._stock_domain(),
            'context': {'group_by': ['product_category_id']},
            'target': 'current',
        }

    def action_view_recent_movements(self):
        self.ensure_one()
        return self._limited_action(
            'Recent Stock Movements', 'stocksense.movement', self._recent_movement_domain()
        )

    def action_view_recent_receipts(self):
        self.ensure_one()
        return self._limited_action(
            'Recent Receipts', 'stocksense.operation', self._recent_operation_domain('receipt')
        )

    def action_view_recent_deliveries(self):
        self.ensure_one()
        return self._limited_action(
            'Recent Deliveries',
            'stocksense.operation',
            self._recent_operation_domain('delivery'),
        )

    def action_view_recent_transfers(self):
        self.ensure_one()
        return self._limited_action(
            'Recent Internal Transfers',
            'stocksense.operation',
            self._recent_operation_domain('internal'),
        )





