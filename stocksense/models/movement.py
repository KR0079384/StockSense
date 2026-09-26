# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError


class StockSenseMovement(models.Model):
    """Inventory movement / ledger entry.

    This is the append-only audit log of all stock changes. Each movement
    records exactly what happened: which product moved, from where, to where,
    how much, when, why, and who was responsible.

    Movements are NEVER manually created by users — they are generated
    exclusively by validated operations. They are also never modified or
    deleted after creation, ensuring a tamper-proof audit trail.
    """
    _name = 'stocksense.movement'
    _description = 'Stock Movement (Ledger Entry)'
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        compute='_compute_name',
        store=True,
    )
    product_id = fields.Many2one(
        'stocksense.product',
        string='Product',
        required=True,
        readonly=True,
        index=True,
        ondelete='restrict',
    )
    source_location_id = fields.Many2one(
        'stocksense.location',
        string='Source Location',
        required=True,
        readonly=True,
        index=True,
        ondelete='restrict',
    )
    destination_location_id = fields.Many2one(
        'stocksense.location',
        string='Destination Location',
        required=True,
        readonly=True,
        index=True,
        ondelete='restrict',
    )
    quantity = fields.Float(
        string='Quantity',
        required=True,
        readonly=True,
        digits=(12, 2),
    )
    uom = fields.Selection(
        related='product_id.uom',
        string='Unit of Measure',
        readonly=True,
        store=True,
    )
    movement_type = fields.Selection(
        selection=[
            ('receipt', 'Receipt'),
            ('delivery', 'Delivery'),
            ('internal', 'Internal Transfer'),
            ('adjustment_in', 'Adjustment (Stock In)'),
            ('adjustment_out', 'Adjustment (Stock Out)'),
        ],
        string='Movement Type',
        required=True,
        readonly=True,
        index=True,
    )
    operation_id = fields.Many2one(
        'stocksense.operation',
        string='Source Operation',
        required=True,
        readonly=True,
        index=True,
        ondelete='restrict',
        help='The business operation that generated this movement.',
    )
    date = fields.Datetime(
        string='Movement Date',
        default=fields.Datetime.now,
        required=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        'res.users',
        string='Performed By',
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )
    reason = fields.Text(
        string='Reason',
        readonly=True,
    )

    # Denormalized fields for efficient dashboard queries
    product_sku = fields.Char(
        related='product_id.sku',
        string='Product SKU',
        store=True,
        readonly=True,
    )
    product_category_id = fields.Many2one(
        related='product_id.category_id',
        string='Product Category',
        store=True,
        readonly=True,
    )
    source_warehouse_id = fields.Many2one(
        related='source_location_id.warehouse_id',
        string='Source Warehouse',
        store=True,
        readonly=True,
    )
    dest_warehouse_id = fields.Many2one(
        related='destination_location_id.warehouse_id',
        string='Destination Warehouse',
        store=True,
        readonly=True,
    )

    @api.depends('operation_id.name', 'movement_type')
    def _compute_name(self):
        for movement in self:
            op_name = movement.operation_id.name or ''
            type_label = dict(
                self._fields['movement_type'].selection
            ).get(movement.movement_type, '')
            movement.name = '%s (%s)' % (op_name, type_label)

    # ──────────────────────────────────────────────────────────────────
    # Immutability enforcement
    # ──────────────────────────────────────────────────────────────────

    def write(self, vals):
        """Prevent modification of movement records.

        Movements are append-only. Only system-computed fields (name) can change.
        """
        allowed_fields = {'name'}
        actual_fields = set(vals.keys())
        forbidden = actual_fields - allowed_fields
        if forbidden:
            raise UserError(
                'Movement records are immutable and cannot be modified. '
                'Fields attempted: %s' % ', '.join(forbidden)
            )
        return super().write(vals)

    def unlink(self):
        """Prevent deletion of movement records."""
        raise UserError(
            'Movement records cannot be deleted. '
            'They form the immutable audit trail.'
        )

    # ──────────────────────────────────────────────────────────────────
    # Stock Balance Update
    # ──────────────────────────────────────────────────────────────────

    def _update_stock_balances(self):
        """Update stock balance records based on this movement.

        For physical (internal) locations:
        - Decrease balance at source location
        - Increase balance at destination location

        Virtual locations (supplier, customer, adjustment) are not tracked
        in the balance table since they represent external entities.
        """
        self.ensure_one()
        Stock = self.env['stocksense.stock']

        # Decrease stock at source if it's a physical location
        if self.source_location_id.location_type == 'internal':
            Stock._update_quantity(
                self.product_id.id,
                self.source_location_id.id,
                -self.quantity,
            )

        # Increase stock at destination if it's a physical location
        if self.destination_location_id.location_type == 'internal':
            Stock._update_quantity(
                self.product_id.id,
                self.destination_location_id.id,
                self.quantity,
            )
