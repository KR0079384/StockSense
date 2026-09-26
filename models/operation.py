# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class StockSenseOperation(models.Model):
    """Inventory operation / business document.

    Represents a business intent such as receiving goods, shipping an order,
    transferring stock between locations, or adjusting inventory counts.

    Operations support multiple lines (multi-product operations) and follow
    a strict lifecycle:
        draft → confirmed → done (or cancelled at any point before done)

    When an operation transitions to 'done', it creates corresponding
    inventory movement(s) for all lines and updates stock balances atomically.
    """
    _name = 'stocksense.operation'
    _description = 'Inventory Operation'
    _order = 'date desc, id desc'
    _inherit = ['mail.thread']

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default='New',
        index=True,
    )
    operation_type = fields.Selection(
        selection=[
            ('receipt', 'Receipt'),
            ('delivery', 'Delivery'),
            ('internal', 'Internal Transfer'),
            ('adjustment', 'Adjustment'),
        ],
        string='Operation Type',
        required=True,
        index=True,
        tracking=True,
    )
    adjustment_type = fields.Selection(
        selection=[
            ('gain', 'Stock Gain'),
            ('loss', 'Stock Loss'),
        ],
        string='Adjustment Direction',
        tracking=True,
        help='Explicit direction for inventory adjustment operations.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('confirmed', 'Confirmed'),
            ('done', 'Done'),
            ('cancelled', 'Cancelled'),
        ],
        string='Status',
        default='draft',
        required=True,
        readonly=True,
        index=True,
        tracking=True,
        copy=False,
    )
    date = fields.Datetime(
        string='Scheduled Date',
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )
    date_done = fields.Datetime(
        string='Completed Date',
        readonly=True,
        copy=False,
    )

    # Multi-product operation lines
    line_ids = fields.One2many(
        'stocksense.operation.line',
        'operation_id',
        string='Operation Lines',
        copy=True,
    )

    # Computed primary product & total quantity for summary / backward compatibility
    product_id = fields.Many2one(
        'stocksense.product',
        string='Primary Product',
        compute='_compute_summary_fields',
        store=True,
        readonly=True,
        index=True,
        tracking=True,
    )
    quantity = fields.Float(
        string='Total Quantity',
        compute='_compute_summary_fields',
        store=True,
        readonly=True,
        digits=(12, 2),
        tracking=True,
    )
    uom = fields.Selection(
        related='product_id.uom',
        string='Unit of Measure',
        readonly=True,
        store=True,
    )

    source_location_id = fields.Many2one(
        'stocksense.location',
        string='Source Location',
        index=True,
        tracking=True,
        help='Where the stock is coming from.',
    )
    destination_location_id = fields.Many2one(
        'stocksense.location',
        string='Destination Location',
        index=True,
        tracking=True,
        help='Where the stock is going to.',
    )
    partner_name = fields.Char(
        string='Partner / Vendor / Customer',
        help='Name of the supplier or customer for receipt/delivery operations.',
    )
    reason = fields.Text(
        string='Reason / Notes',
        help='Reason for the operation, especially for adjustments.',
    )
    responsible_user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        tracking=True,
    )
    movement_ids = fields.One2many(
        'stocksense.movement',
        'operation_id',
        string='Movements',
        readonly=True,
    )
    movement_count = fields.Integer(
        string='Movement Count',
        compute='_compute_movement_count',
    )

    @api.depends('line_ids.product_id', 'line_ids.quantity')
    def _compute_summary_fields(self):
        for op in self:
            if op.line_ids:
                op.product_id = op.line_ids[0].product_id
                op.quantity = sum(line.quantity for line in op.line_ids)
            else:
                op.product_id = False
                op.quantity = 0.0

    def _compute_movement_count(self):
        for operation in self:
            operation.movement_count = len(operation.movement_ids)

    # ──────────────────────────────────────────────────────────────────
    # CRUD Overrides
    # ──────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """Assign sequence-based reference and auto-create line if product_id is passed."""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                op_type = vals.get('operation_type', 'receipt')
                seq_code = 'stocksense.operation.%s' % op_type
                vals['name'] = self.env['ir.sequence'].next_by_code(seq_code) or 'New'

            # Backward compatibility: convert single product_id/quantity into a line if line_ids is not set
            if ('product_id' in vals or 'quantity' in vals) and not vals.get('line_ids'):
                prod_id = vals.get('product_id')
                qty = vals.get('quantity', 1.0)
                if prod_id:
                    vals['line_ids'] = [(0, 0, {'product_id': prod_id, 'quantity': qty})]
                    # Remove direct product_id and quantity from vals to avoid write conflicts on computed fields
                    vals.pop('product_id', None)
                    vals.pop('quantity', None)

        return super().create(vals_list)

    def unlink(self):
        """Only draft operations can be deleted."""
        for operation in self:
            if operation.state != 'draft':
                raise UserError(
                    'You can only delete operations in draft state. '
                    'Cancel the operation first if needed.'
                )
        return super().unlink()

    # ──────────────────────────────────────────────────────────────────
    # Constraints
    # ──────────────────────────────────────────────────────────────────

    @api.constrains('source_location_id', 'destination_location_id', 'operation_type', 'adjustment_type')
    def _check_locations(self):
        """Validate location and adjustment type requirements based on operation type."""
        for op in self:
            if op.operation_type == 'receipt':
                if not op.destination_location_id:
                    raise ValidationError(
                        'Receipt operations require a destination location.'
                    )
                if op.destination_location_id.location_type != 'internal':
                    raise ValidationError(
                        'Receipt destination must be an internal location.'
                    )
            elif op.operation_type == 'delivery':
                if not op.source_location_id:
                    raise ValidationError(
                        'Delivery operations require a source location.'
                    )
                if op.source_location_id.location_type != 'internal':
                    raise ValidationError(
                        'Delivery source must be an internal location.'
                    )
            elif op.operation_type == 'internal':
                if not op.source_location_id or not op.destination_location_id:
                    raise ValidationError(
                        'Internal transfers require both source and destination locations.'
                    )
                if op.source_location_id == op.destination_location_id:
                    raise ValidationError(
                        'Cannot transfer stock from a location to itself.'
                    )
                if op.source_location_id.location_type != 'internal':
                    raise ValidationError(
                        'Transfer source must be an internal location.'
                    )
                if op.destination_location_id.location_type != 'internal':
                    raise ValidationError(
                        'Transfer destination must be an internal location.'
                    )
            elif op.operation_type == 'adjustment':
                if not op.adjustment_type:
                    raise ValidationError(
                        'Adjustment operations require an explicit direction (gain or loss).'
                    )
                if op.adjustment_type == 'gain':
                    if not op.destination_location_id:
                        raise ValidationError(
                            'Stock Gain adjustment requires a target destination location.'
                        )
                    if op.destination_location_id.location_type != 'internal':
                        raise ValidationError(
                            'Stock Gain destination must be an internal location.'
                        )
                elif op.adjustment_type == 'loss':
                    if not op.source_location_id:
                        raise ValidationError(
                            'Stock Loss adjustment requires a source location.'
                        )
                    if op.source_location_id.location_type != 'internal':
                        raise ValidationError(
                            'Stock Loss source must be an internal location.'
                        )

    # ──────────────────────────────────────────────────────────────────
    # State Transitions
    # ──────────────────────────────────────────────────────────────────

    def action_confirm(self):
        """Move operation from draft to confirmed."""
        for operation in self:
            if operation.state != 'draft':
                raise UserError('Only draft operations can be confirmed.')
            if not operation.line_ids:
                raise ValidationError('Operation %s must contain at least one operation line.' % operation.name)
            operation.state = 'confirmed'

    def action_validate(self):
        """Validate the operation: transition to done, create movements, update stock atomically.

        This is the critical method that bridges business operations
        to the movement ledger and stock balances.
        """
        for operation in self:
            if operation.state not in ('draft', 'confirmed'):
                raise UserError(
                    'Only draft or confirmed operations can be validated.'
                )
            operation._create_movements()
            operation.write({
                'state': 'done',
                'date_done': fields.Datetime.now(),
            })

    def action_cancel(self):
        """Cancel the operation. Done operations cannot be cancelled."""
        for operation in self:
            if operation.state == 'done':
                raise UserError(
                    'Cannot cancel a completed operation. '
                    'Create a reverse operation instead.'
                )
            operation.state = 'cancelled'

    def action_draft(self):
        """Reset a cancelled operation back to draft."""
        for operation in self:
            if operation.state != 'cancelled':
                raise UserError('Only cancelled operations can be reset to draft.')
            operation.state = 'draft'

    # ──────────────────────────────────────────────────────────────────
    # Movement Creation (Core Business Logic - Multi-Line & Atomic)
    # ──────────────────────────────────────────────────────────────────

    def _get_location_ref(self, xml_id):
        """Helper to safely fetch virtual location xml_id regardless of module name casing."""
        try:
            return self.env.ref('StockSense.' + xml_id)
        except ValueError:
            return self.env.ref('stocksense.' + xml_id)

    def _create_movements(self):
        """Create inventory movement(s) for this operation.

        Supports multi-line operations. Each line creates a distinct movement.
        Operation validation and movement creation are strictly atomic.
        """
        self.ensure_one()
        if not self.line_ids:
            raise ValidationError('Operation %s must contain at least one operation line.' % self.name)

        Movement = self.env['stocksense.movement']

        if self.operation_type == 'receipt':
            supplier_loc = self._get_location_ref('location_suppliers')
            source = self.source_location_id or supplier_loc
            destination = self.destination_location_id
            move_type = 'receipt'

        elif self.operation_type == 'delivery':
            customer_loc = self._get_location_ref('location_customers')
            source = self.source_location_id
            destination = self.destination_location_id or customer_loc
            move_type = 'delivery'

        elif self.operation_type == 'internal':
            source = self.source_location_id
            destination = self.destination_location_id
            move_type = 'internal'

        elif self.operation_type == 'adjustment':
            if not self.adjustment_type:
                raise ValidationError('Adjustment operations require an explicit adjustment direction (gain or loss).')
            adjustment_loc = self._get_location_ref('location_adjustment')
            if self.adjustment_type == 'gain':
                source = adjustment_loc
                destination = self.destination_location_id
                move_type = 'adjustment_in'
            elif self.adjustment_type == 'loss':
                source = self.source_location_id
                destination = adjustment_loc
                move_type = 'adjustment_out'
            else:
                raise UserError('Unknown adjustment type: %s' % self.adjustment_type)
        else:
            raise UserError('Unknown operation type: %s' % self.operation_type)

        # Atomically check stock availability at source location for all lines
        if source and source.location_type == 'internal':
            self._check_all_lines_stock_availability(source)

        # Create movement for each line and update stock balances
        movements = self.env['stocksense.movement']
        for line in self.line_ids:
            movement = Movement.create({
                'product_id': line.product_id.id,
                'source_location_id': source.id,
                'destination_location_id': destination.id,
                'quantity': line.quantity,
                'movement_type': move_type,
                'operation_id': self.id,
                'operation_line_id': line.id,
                'user_id': self.env.user.id,
                'reason': self.reason,
            })
            movement._update_stock_balances()
            movements |= movement

        return movements

    def _check_all_lines_stock_availability(self, location):
        """Verify sufficient stock exists at location for all lines combined atomically."""
        self.ensure_one()
        needed_by_product = {}
        for line in self.line_ids:
            needed_by_product[line.product_id] = needed_by_product.get(line.product_id, 0.0) + line.quantity

        for product, needed in needed_by_product.items():
            stock = self.env['stocksense.stock'].search([
                ('product_id', '=', product.id),
                ('location_id', '=', location.id),
            ], limit=1)
            available = stock.quantity if stock else 0.0
            if available < needed:
                raise UserError(
                    'Insufficient stock at %s for product "%s".\n'
                    'Available: %.2f %s\n'
                    'Required: %.2f %s'
                    % (
                        location.complete_name or location.name,
                        product.name,
                        available, product.uom,
                        needed, product.uom,
                    )
                )

    def action_view_movements(self):
        """Open movements created by this operation."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Movements for %s' % self.name,
            'res_model': 'stocksense.movement',
            'view_mode': 'tree,form',
            'domain': [('operation_id', '=', self.id)],
        }
