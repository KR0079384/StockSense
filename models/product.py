# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockSenseProduct(models.Model):
    """Product master data.

    Each product has a unique SKU, belongs to a category, and defines
    a unit of measure. Products are the core entity that all inventory
    operations reference.
    """
    _name = 'stocksense.product'
    _description = 'Product'
    _order = 'name'

    name = fields.Char(
        string='Product Name',
        required=True,
        index=True,
    )
    sku = fields.Char(
        string='SKU / Internal Reference',
        required=True,
        index=True,
        copy=False,
        help='Unique Stock Keeping Unit identifier.',
    )
    category_id = fields.Many2one(
        'stocksense.category',
        string='Category',
        required=True,
        index=True,
        ondelete='restrict',
    )
    description = fields.Text(string='Description')
    uom = fields.Selection(
        selection=[
            ('unit', 'Units'),
            ('kg', 'Kilograms'),
            ('g', 'Grams'),
            ('l', 'Liters'),
            ('ml', 'Milliliters'),
            ('m', 'Meters'),
            ('cm', 'Centimeters'),
            ('box', 'Boxes'),
            ('pair', 'Pairs'),
            ('dozen', 'Dozens'),
        ],
        string='Unit of Measure',
        default='unit',
        required=True,
    )
    weight = fields.Float(string='Weight (kg)', digits=(10, 3))
    volume = fields.Float(string='Volume (m³)', digits=(10, 4))
    barcode = fields.Char(string='Barcode', index=True, copy=False)
    image = fields.Binary(string='Product Image', attachment=True)
    active = fields.Boolean(default=True)
    notes = fields.Text(string='Internal Notes')

    # Computed stock fields for quick access
    total_stock = fields.Float(
        string='Total Stock',
        compute='_compute_total_stock',
        search='_search_total_stock',
        store=False,
        digits=(12, 2),
        help='Total quantity across all internal locations.',
    )

    # Related records
    stock_ids = fields.One2many(
        'stocksense.stock',
        'product_id',
        string='Stock Balances',
    )
    movement_ids = fields.One2many(
        'stocksense.movement',
        'product_id',
        string='Stock Movements',
    )
    reorder_rule_ids = fields.One2many(
        'stocksense.reorder.rule',
        'product_id',
        string='Reorder Rules',
    )

    def _compute_total_stock(self):
        """Compute total stock across all internal locations."""
        for product in self:
            stocks = self.env['stocksense.stock'].search([
                ('product_id', '=', product.id),
                ('location_id.location_type', '=', 'internal'),
            ])
            product.total_stock = sum(stocks.mapped('quantity'))

    def _search_total_stock(self, operator, value):
        matching_product_ids = []
        for product in self.search([]):
            if (operator in ('>', '&gt;') and product.total_stock > value) or \
               (operator in ('>=', '&gt;=') and product.total_stock >= value) or \
               (operator in ('<', '&lt;') and product.total_stock < value) or \
               (operator in ('<=', '&lt;=') and product.total_stock <= value) or \
               (operator in ('=', '==') and product.total_stock == value) or \
               (operator in ('!=', '<>') and product.total_stock != value):
                matching_product_ids.append(product.id)
        return [('id', 'in', matching_product_ids)]

    @api.constrains('weight')
    def _check_weight(self):
        for product in self:
            if product.weight < 0:
                raise ValidationError('Product weight cannot be negative.')

    @api.constrains('volume')
    def _check_volume(self):
        for product in self:
            if product.volume < 0:
                raise ValidationError('Product volume cannot be negative.')

    _sql_constraints = [
        ('sku_unique', 'UNIQUE(sku)',
         'SKU must be unique. A product with this SKU already exists.'),
        ('barcode_unique', 'UNIQUE(barcode)',
         'Barcode must be unique. A product with this barcode already exists.'),
    ]

    def name_get(self):
        result = []
        for product in self:
            name = '[%s] %s' % (product.sku, product.name)
            result.append((product.id, name))
        return result
