# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError


class StockSenseOperation(models.Model):
    """Inventory operation / business document.

    Represents a business intent such as receiving goods, shipping an order,
    transferring stock between locations, or adjusting inventory counts.

    Operations follow a strict lifecycle:
        draft → confirmed → done (or cancelled at any point before done)

    When an operation transitions to 'done', it creates the corresponding
    inventory movement(s) and updates stock balances.
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
        readonly=True,
        states={'draft': [('readonly', False)]},
        index=True,
        tracking=True,
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
        readonly=True,
        states={'draft': [('readonly', False)]},
        tracking=True,
    )
    date_done = fields.Datetime(
        string='Completed Date',
        readonly=True,
        copy=False,
    )
    product_id = fields.Many2one(
        'stocksense.product',
        string='Product',
        required=True,
        readonly=True,
        states={'draft': [('readonly', False)]},
        index=True,
        tracking=True,
    )
    quantity = fields.Float(
        string='Quantity',
        required=True,
        digits=(12, 2),
        readonly=True,
        states={'draft': [('readonly', False)]},
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
        readonly=True,
        states={'draft': [('readonly', False)]},
        index=True,
        tracking=True,
        help='Where the stock is coming from.',
    )
    destination_location_id = fields.Many2one(
        'stocksense.location',
        string='Destination Location',
        readonly=True,
        states={'draft': [('readonly', False)]},
        index=True,
        tracking=True,
        help='Where the stock is going to.',
    )
    partner_name = fields.Char(
        string='Partner / Vendor / Customer',
        readonly=True,
        states={'draft': [('readonly', False)]},
        help='Name of the supplier or customer for receipt/delivery operations.',
    )
    reason = fields.Text(
        string='Reason / Notes',
        readonly=True,
        states={'draft': [('readonly', False)]},
        help='Reason for the operation, especially for adjustments.',
    )
    responsible_user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        readonly=True,
        states={'draft': [('readonly', False)]},
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

    def _compute_movement_count(self):
        for operation in self:
            operation.movement_count = len(operation.movement_ids)

    # ──────────────────────────────────────────────────────────────────
    # CRUD Overrides
    # ──────────────────────────────────────────────────────────────────

    @api.model_create_multi
    def create(self, vals_list):
        """Assign sequence-based reference on creation."""
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                op_type = vals.get('operation_type', 'receipt')
                seq_code = 'stocksense.operation.%s' % op_type
                vals['name'] = self.env['ir.sequence'].next_by_code(seq_code) or 'New'
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

    @api.constrains('quantity')
    def _check_quantity_positive(self):
        for operation in self:
            if operation.quantity <= 0:
                raise ValidationError(
                    'Quantity must be a positive number (got %.2f).'
                    % operation.quantity
                )

    @api.constrains('source_location_id', 'destination_location_id', 'operation_type')
    def _check_locations(self):
        """Validate location requirements based on operation type."""
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
                if not op.destination_location_id:
                    raise ValidationError(
                        'Adjustment operations require a target location '
                        '(destination for gain, source for loss).'
                    )

    # ──────────────────────────────────────────────────────────────────
    # State Transitions
    # ──────────────────────────────────────────────────────────────────

    def action_confirm(self):
        """Move operation from draft to confirmed."""
        for operation in self:
            if operation.state != 'draft':
                raise UserError('Only draft operations can be confirmed.')
            operation.state = 'confirmed'

    def action_validate(self):
        """Validate the operation: transition to done, create movements, update stock.

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
    # Movement Creation (Core Business Logic)
    # ──────────────────────────────────────────────────────────────────

    def _create_movements(self):
        """Create inventory movement(s) for this operation.

        Each operation type resolves to a specific source/destination pair.
        The movement is then created and stock balances are updated atomically.
        """
        self.ensure_one()
        Movement = self.env['stocksense.movement']

        if self.operation_type == 'receipt':
            # Supplier (virtual) → Internal location
            supplier_loc = self.env.ref('stocksense.location_suppliers')
            source = self.source_location_id or supplier_loc
            destination = self.destination_location_id
            move_type = 'receipt'

        elif self.operation_type == 'delivery':
            # Internal location → Customer (virtual)
            customer_loc = self.env.ref('stocksense.location_customers')
            source = self.source_location_id
            destination = self.destination_location_id or customer_loc
            move_type = 'delivery'

        elif self.operation_type == 'internal':
            # Internal location → Internal location
            source = self.source_location_id
            destination = self.destination_location_id
            move_type = 'internal'

            # Check sufficient stock at source
            self._check_stock_availability(source)

        elif self.operation_type == 'adjustment':
            adjustment_loc = self.env.ref('stocksense.location_adjustment')
            target = self.destination_location_id
            # Determine if this is stock gain or loss based on quantity context
            # Positive qty on an adjustment = stock correction at the target location
            # We'll use reason field to differentiate, but by default treat as stock-in
            # For stock loss, user creates an adjustment with source = internal location
            if self.source_location_id and self.source_location_id.location_type == 'internal':
                # Stock loss: internal → adjustment virtual
                source = self.source_location_id
                destination = adjustment_loc
                move_type = 'adjustment_out'
                self._check_stock_availability(source)
            else:
                # Stock gain: adjustment virtual → internal
                source = adjustment_loc
                destination = target
                move_type = 'adjustment_in'
        else:
            raise UserError('Unknown operation type: %s' % self.operation_type)

        # Create the movement record
        movement = Movement.create({
            'product_id': self.product_id.id,
            'source_location_id': source.id,
            'destination_location_id': destination.id,
            'quantity': self.quantity,
            'movement_type': move_type,
            'operation_id': self.id,
            'user_id': self.env.user.id,
            'reason': self.reason,
        })

        # Update stock balances
        movement._update_stock_balances()

        return movement

    def _check_stock_availability(self, location):
        """Verify sufficient stock exists at the given location."""
        self.ensure_one()
        stock = self.env['stocksense.stock'].search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', location.id),
        ], limit=1)
        available = stock.quantity if stock else 0.0
        if available < self.quantity:
            raise UserError(
                'Insufficient stock at %s.\n'
                'Available: %.2f %s\n'
                'Required: %.2f %s'
                % (
                    location.complete_name or location.name,
                    available, self.product_id.uom,
                    self.quantity, self.product_id.uom,
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
