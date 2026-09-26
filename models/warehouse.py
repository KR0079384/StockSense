# -*- coding: utf-8 -*-
from odoo import models, fields, api


class StockSenseWarehouse(models.Model):
    """Physical warehouse.

    Each warehouse represents a distinct physical storage facility.
    Creating a warehouse automatically generates a default 'Stock' location
    as a child, along with Input and Output locations for receiving/shipping.
    """
    _name = 'stocksense.warehouse'
    _description = 'Warehouse'
    _order = 'name'

    name = fields.Char(
        string='Warehouse Name',
        required=True,
        index=True,
    )
    code = fields.Char(
        string='Short Code',
        required=True,
        size=5,
        help='Short code for the warehouse, used in references (e.g., WH, WH2).',
    )
    address = fields.Text(string='Address')
    active = fields.Boolean(default=True)

    # Auto-generated locations
    lot_stock_id = fields.Many2one(
        'stocksense.location',
        string='Default Stock Location',
        readonly=True,
        help='Main stock location for this warehouse, created automatically.',
    )
    location_ids = fields.One2many(
        'stocksense.location',
        'warehouse_id',
        string='Locations',
    )

    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)',
         'Warehouse code must be unique.'),
        ('name_unique', 'UNIQUE(name)',
         'Warehouse name must be unique.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to auto-generate default locations for each warehouse."""
        warehouses = super().create(vals_list)
        Location = self.env['stocksense.location']
        for warehouse in warehouses:
            # Create the main stock location
            stock_loc = Location.create({
                'name': 'Stock',
                'warehouse_id': warehouse.id,
                'location_type': 'internal',
                'is_default': True,
            })
            warehouse.lot_stock_id = stock_loc.id

            # Create input location (for receiving)
            Location.create({
                'name': 'Input',
                'warehouse_id': warehouse.id,
                'location_type': 'internal',
                'parent_id': stock_loc.id,
            })
            # Create output location (for shipping)
            Location.create({
                'name': 'Output',
                'warehouse_id': warehouse.id,
                'location_type': 'internal',
                'parent_id': stock_loc.id,
            })
        return warehouses
