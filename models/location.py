# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockSenseLocation(models.Model):
    """Inventory location with hierarchical support.

    Locations represent physical or virtual places where stock can reside.
    Physical (internal) locations belong to a warehouse and can be nested.
    Virtual locations (supplier, customer, adjustment) represent external
    entities for the double-entry ledger model.
    """
    _name = 'stocksense.location'
    _description = 'Stock Location'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'complete_name'

    name = fields.Char(
        string='Location Name',
        required=True,
        index=True,
    )
    complete_name = fields.Char(
        string='Full Location Path',
        compute='_compute_complete_name',
        recursive=True,
        store=True,
    )
    location_type = fields.Selection(
        selection=[
            ('internal', 'Internal Location'),
            ('supplier', 'Supplier Location'),
            ('customer', 'Customer Location'),
            ('adjustment', 'Inventory Adjustment'),
            ('transit', 'Transit Location'),
        ],
        string='Location Type',
        required=True,
        default='internal',
        index=True,
        help=(
            'Internal: physical location within a warehouse.\n'
            'Supplier: virtual location for incoming goods.\n'
            'Customer: virtual location for outgoing goods.\n'
            'Adjustment: virtual location for inventory adjustments.\n'
            'Transit: goods in transit between warehouses.'
        ),
    )
    warehouse_id = fields.Many2one(
        'stocksense.warehouse',
        string='Warehouse',
        index=True,
        ondelete='cascade',
        help='The warehouse this location belongs to. Empty for virtual locations.',
    )
    parent_id = fields.Many2one(
        'stocksense.location',
        string='Parent Location',
        index=True,
        ondelete='cascade',
    )
    parent_path = fields.Char(
        index=True,
        unaccent=False,
    )
    child_ids = fields.One2many(
        'stocksense.location',
        'parent_id',
        string='Sub-locations',
    )
    is_default = fields.Boolean(
        string='Is Default Stock Location',
        default=False,
        help='If set, this is the default stock location for its warehouse.',
    )
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Notes')

    # Computed fields
    stock_count = fields.Integer(
        string='Products in Stock',
        compute='_compute_stock_count',
    )

    @api.depends('name', 'parent_id.complete_name', 'warehouse_id.code')
    def _compute_complete_name(self):
        for location in self:
            if location.parent_id:
                location.complete_name = '%s / %s' % (
                    location.parent_id.complete_name, location.name
                )
            elif location.warehouse_id:
                location.complete_name = '%s / %s' % (
                    location.warehouse_id.code, location.name
                )
            else:
                location.complete_name = location.name

    def _compute_stock_count(self):
        for location in self:
            location.stock_count = self.env['stocksense.stock'].search_count(
                [('location_id', '=', location.id), ('quantity', '>', 0)]
            )

    @api.constrains('parent_id')
    def _check_location_recursion(self):
        if not self._check_recursion():
            raise ValidationError('Error! You cannot create recursive locations.')

    @api.constrains('warehouse_id', 'location_type')
    def _check_warehouse_for_internal(self):
        """Internal locations must belong to a warehouse."""
        for location in self:
            if location.location_type == 'internal' and not location.warehouse_id:
                raise ValidationError(
                    'Internal locations must belong to a warehouse.'
                )

    @property
    def is_physical(self):
        """Returns True if this is a physical (internal) location."""
        return self.location_type == 'internal'

    @property
    def is_virtual(self):
        """Returns True if this is a virtual location (supplier/customer/adjustment)."""
        return self.location_type in ('supplier', 'customer', 'adjustment')

    def name_get(self):
        result = []
        for location in self:
            result.append((location.id, location.complete_name or location.name))
        return result
