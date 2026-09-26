
# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockSenseReorderRule(models.Model):
    """Reorder rule for low-stock detection.

    Defines minimum stock thresholds per product-location pair.
    When stock falls below the minimum, the stock balance record
    is flagged via a computed field for dashboard alerts.
    """
    _name = 'stocksense.reorder.rule'
    _description = 'Reorder Rule'
    _order = 'product_id, location_id'

    product_id = fields.Many2one(
        'stocksense.product',
        string='Product',
        required=True,
        index=True,
        ondelete='cascade',
    )
    location_id = fields.Many2one(
        'stocksense.location',
        string='Location',
        required=True,
        index=True,
        domain=[('location_type', '=', 'internal')],
        ondelete='cascade',
        help='The specific location to monitor stock levels for.',
    )
    warehouse_id = fields.Many2one(
        related='location_id.warehouse_id',
        string='Warehouse',
        store=True,
        readonly=True,
    )
    min_quantity = fields.Float(
        string='Minimum Quantity',
        required=True,
        digits=(12, 2),
        help='When stock falls to or below this level, a reorder alert is triggered.',
    )
    max_quantity = fields.Float(
        string='Maximum Quantity',
        digits=(12, 2),
        help='Suggested reorder-up-to quantity.',
    )
    reorder_quantity = fields.Float(
        string='Reorder Quantity',
        digits=(12, 2),
        help='Default quantity to reorder.',
    )
    active = fields.Boolean(default=True)

    # Computed: current stock level for this rule
    current_stock = fields.Float(
        string='Current Stock',
        compute='_compute_current_stock',
        store=True,
        digits=(12, 2),
    )
    is_triggered = fields.Boolean(
        string='Alert Triggered',
        compute='_compute_current_stock',
        search='_search_is_triggered',
    )

    @api.depends(
        'product_id',
        'location_id',
        'min_quantity',
        'location_id.stock_count',
    )
    def _compute_current_stock(self):
        for rule in self:
            stock = self.env['stocksense.stock'].search([
                ('product_id', '=', rule.product_id.id),
                ('location_id', '=', rule.location_id.id),
            ], limit=1)

            rule.current_stock = stock.quantity if stock else 0.0
            rule.is_triggered = (
                rule.current_stock <= rule.min_quantity
            )

    def _search_is_triggered(self, operator, value):
        """Search reorder rules by their triggered status."""
        if operator not in ('=', '==', '!=', '<>'):
            return [('id', '=', False)]

        # Normalize the requested boolean value.
        expected = bool(value)
        if operator in ('!=', '<>'):
            expected = not expected

        rules = self.search([('active', '=', True)])
        matching_ids = []

        for rule in rules:
            stock = self.env['stocksense.stock'].search([
                ('product_id', '=', rule.product_id.id),
                ('location_id', '=', rule.location_id.id),
            ], limit=1)

            quantity = stock.quantity if stock else 0.0
            triggered = quantity <= rule.min_quantity

            if triggered == expected:
                matching_ids.append(rule.id)

        return [('id', 'in', matching_ids)]

    @api.constrains('min_quantity')
    def _check_min_quantity(self):
        for rule in self:
            if rule.min_quantity < 0:
                raise ValidationError(
                    'Minimum quantity cannot be negative.'
                )

    @api.constrains('max_quantity', 'min_quantity')
    def _check_max_quantity(self):
        for rule in self:
            if (
                rule.max_quantity
                and rule.max_quantity < rule.min_quantity
            ):
                raise ValidationError(
                    'Maximum quantity must be greater than or equal '
                    'to minimum quantity.'
                )

    @api.constrains('reorder_quantity')
    def _check_reorder_quantity(self):
        for rule in self:
            if (
                rule.reorder_quantity
                and rule.reorder_quantity <= 0
            ):
                raise ValidationError(
                    'Reorder quantity must be positive.'
                )

    _sql_constraints = [
        (
            'product_location_unique',
            'UNIQUE(product_id, location_id)',
            'Only one reorder rule per product-location pair is allowed.',
        ),
    ]