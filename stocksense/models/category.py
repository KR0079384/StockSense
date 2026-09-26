# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import ValidationError


class StockSenseCategory(models.Model):
    """Product category with hierarchical support.

    Categories organize products into a tree structure.
    Each category can have a parent and multiple children,
    enabling multi-level classification (e.g., Electronics > Phones > Smartphones).
    """
    _name = 'stocksense.category'
    _description = 'Product Category'
    _parent_name = 'parent_id'
    _parent_store = True
    _order = 'complete_name'

    name = fields.Char(
        string='Category Name',
        required=True,
        index=True,
    )
    complete_name = fields.Char(
        string='Complete Name',
        compute='_compute_complete_name',
        recursive=True,
        store=True,
    )
    parent_id = fields.Many2one(
        'stocksense.category',
        string='Parent Category',
        index=True,
        ondelete='cascade',
    )
    parent_path = fields.Char(
        index=True,
        unaccent=False,
    )
    child_ids = fields.One2many(
        'stocksense.category',
        'parent_id',
        string='Child Categories',
    )
    product_count = fields.Integer(
        string='Product Count',
        compute='_compute_product_count',
    )
    notes = fields.Text(string='Notes')
    active = fields.Boolean(default=True)

    @api.depends('name', 'parent_id.complete_name')
    def _compute_complete_name(self):
        for category in self:
            if category.parent_id:
                category.complete_name = '%s / %s' % (
                    category.parent_id.complete_name, category.name
                )
            else:
                category.complete_name = category.name

    def _compute_product_count(self):
        for category in self:
            category.product_count = self.env['stocksense.product'].search_count(
                [('category_id', '=', category.id)]
            )

    @api.constrains('parent_id')
    def _check_category_recursion(self):
        if not self._check_recursion():
            raise ValidationError('Error! You cannot create recursive categories.')

    _sql_constraints = [
        ('name_parent_unique',
         'UNIQUE(name, parent_id)',
         'Category name must be unique within the same parent category.'),
    ]
