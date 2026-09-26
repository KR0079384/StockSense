# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockSenseOperationLine(models.Model):
    """Line item for inventory operations.

    An operation line represents a specific product and quantity being moved,
    received, delivered, or adjusted as part of a parent business operation.
    """
    _name = 'stocksense.operation.line'
    _description = 'Inventory Operation Line'
    _order = 'id asc'

    operation_id = fields.Many2one(
        'stocksense.operation',
        string='Operation',
        required=True,
        ondelete='cascade',
        index=True,
    )
    product_id = fields.Many2one(
        'stocksense.product',
        string='Product',
        required=True,
        index=True,
        ondelete='restrict',
    )
    quantity = fields.Float(
        string='Quantity',
        required=True,
        default=1.0,
        digits=(12, 2),
    )
    uom = fields.Selection(
        related='product_id.uom',
        string='Unit of Measure',
        readonly=True,
        store=True,
    )
    state = fields.Selection(
        related='operation_id.state',
        string='Status',
        store=True,
        readonly=True,
    )

    @api.constrains('quantity')
    def _check_quantity_positive(self):
        for line in self:
            if line.quantity <= 0:
                raise ValidationError(
                    'Line quantity must be a positive number (got %.2f).'
                    % line.quantity
                )
