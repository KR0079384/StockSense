# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockSenseStock(models.Model):
    """Current stock balance per product per location.

    This is the cached/materialized view of current inventory levels.
    It is updated atomically whenever a movement is created.

    The balance can always be verified against the movement ledger:
        sum(movements to this location) - sum(movements from this location)
        should equal the stored quantity.
    """
    _name = 'stocksense.stock'
    _description = 'Stock Balance'
    _order = 'product_id, location_id'

    product_id = fields.Many2one(
        'stocksense.product',
        string='Product',
        required=True,
        readonly=True,
        index=True,
        ondelete='cascade',
    )
    location_id = fields.Many2one(
        'stocksense.location',
        string='Location',
        required=True,
        readonly=True,
        index=True,
        ondelete='cascade',
    )
    quantity = fields.Float(
        string='On Hand Quantity',
        digits=(12, 2),
        default=0.0,
        readonly=True,
    )
    uom = fields.Selection(
        related='product_id.uom',
        string='Unit of Measure',
        readonly=True,
        store=True,
    )

    # Denormalized fields for efficient queries
    product_name = fields.Char(
        related='product_id.name',
        string='Product Name',
        store=True,
        readonly=True,
    )
    product_sku = fields.Char(
        related='product_id.sku',
        string='Product SKU',
        store=True,
        readonly=True,
    )
    product_category_id = fields.Many2one(
        related='product_id.category_id',
        string='Category',
        store=True,
        readonly=True,
    )
    warehouse_id = fields.Many2one(
        related='location_id.warehouse_id',
        string='Warehouse',
        store=True,
        readonly=True,
    )
    location_name = fields.Char(
        related='location_id.complete_name',
        string='Location Path',
        store=True,
        readonly=True,
    )

    # Reorder alert computed field
    is_below_reorder = fields.Boolean(
        string='Below Reorder Level',
        compute='_compute_reorder_status',
        store=False,
    )
    reorder_min_qty = fields.Float(
        string='Reorder Minimum',
        compute='_compute_reorder_status',
        store=False,
    )

    def _compute_reorder_status(self):
        """Check if current stock is below any applicable reorder rule."""
        for stock in self:
            rule = self.env['stocksense.reorder.rule'].search([
                ('product_id', '=', stock.product_id.id),
                ('location_id', '=', stock.location_id.id),
                ('active', '=', True),
            ], limit=1)
            if rule:
                stock.is_below_reorder = stock.quantity <= rule.min_quantity
                stock.reorder_min_qty = rule.min_quantity
            else:
                stock.is_below_reorder = False
                stock.reorder_min_qty = 0.0

    _sql_constraints = [
        ('product_location_unique',
         'UNIQUE(product_id, location_id)',
         'Stock balance must be unique per product-location pair.'),
    ]

    @api.model
    def _update_quantity(self, product_id, location_id, qty_change):
        """Update the stock balance for a product at a location.

        Creates the balance record if it doesn't exist yet.
        This method is called exclusively by Movement._update_stock_balances().

        Args:
            product_id: int - product record ID
            location_id: int - location record ID
            qty_change: float - quantity to add (positive) or subtract (negative)
        """
        stock = self.search([
            ('product_id', '=', product_id),
            ('location_id', '=', location_id),
        ], limit=1)

        if stock:
            # Use SQL for atomic update to avoid race conditions
            self.env.cr.execute(
                """
                UPDATE stocksense_stock
                SET quantity = quantity + %s
                WHERE id = %s
                RETURNING quantity
                """,
                (qty_change, stock.id)
            )
            stock.invalidate_recordset(['quantity'])
        else:
            self.create({
                'product_id': product_id,
                'location_id': location_id,
                'quantity': qty_change,
            })

    def action_view_movements(self):
        """Open the movement history for this product at this location."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Movement History',
            'res_model': 'stocksense.movement',
            'view_mode': 'tree,form',
            'domain': [
                '|',
                ('source_location_id', '=', self.location_id.id),
                ('destination_location_id', '=', self.location_id.id),
                ('product_id', '=', self.product_id.id),
            ],
            'context': {'default_product_id': self.product_id.id},
        }

    def name_get(self):
        result = []
        for stock in self:
            name = '%s @ %s: %.2f %s' % (
                stock.product_id.name,
                stock.location_id.complete_name or stock.location_id.name,
                stock.quantity,
                stock.uom or '',
            )
            result.append((stock.id, name))
        return result
