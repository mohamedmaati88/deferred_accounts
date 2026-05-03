from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class AccountDeferredLine(models.Model):
    _name = 'account.deferred.line'
    _description = 'Deferred Expense/Revenue Recognition Schedule'
    _order = 'date, id'
    _rec_name = 'name'

    name = fields.Char(string='Reference', required=True)
    is_initial = fields.Boolean(
        default=False,
        help='True for the initial deferral entry (expense → deferred account).',
    )
    invoice_line_id = fields.Many2one(
        'account.move.line',
        string='Invoice Line',
        required=True,
        ondelete='cascade',
        index=True,
    )
    invoice_id = fields.Many2one(
        'account.move',
        related='invoice_line_id.move_id',
        store=True,
        string='Invoice',
    )
    company_id = fields.Many2one(
        'res.company',
        related='invoice_id.company_id',
        store=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='invoice_id.currency_id',
        store=True,
    )
    deferred_type = fields.Selection(
        [('expense', 'Deferred Expense'), ('revenue', 'Deferred Revenue')],
        string='Type',
        required=True,
    )
    date = fields.Date(string='Date', required=True, index=True)
    amount = fields.Monetary(string='Amount', currency_field='currency_id', required=True)
    # Amount in the invoice currency (equals amount when no foreign currency)
    amount_currency = fields.Monetary(
        string='Amount in Currency',
        currency_field='currency_id',
    )
    partner_id = fields.Many2one('res.partner', string='Partner')
    analytic_distribution = fields.Json('Analytic Distribution')
    recognition_account_id = fields.Many2one(
        'account.account',
        string='Recognition Account',
        required=True,
    )
    deferred_account_id = fields.Many2one(
        'account.account',
        string='Deferred Account',
        required=True,
    )
    move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    state = fields.Selection(
        [('draft', 'Draft'), ('posted', 'Posted'), ('cancelled', 'Cancelled')],
        string='Status',
        default='draft',
        required=True,
        index=True,
    )

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_('The recognition amount must be greater than zero.'))

    def action_post(self):
        for rec in self.filtered(lambda r: r.state == 'draft' and not r.is_initial):
            if rec.move_id:
                rec.move_id.action_post()
            else:
                move = rec._create_recognition_entry()
                move.action_post()
                rec.move_id = move
            rec.state = 'posted'

    def action_reset_to_draft(self):
        for rec in self.filtered(lambda r: r.state == 'posted' and not r.is_initial):
            if rec.move_id and rec.move_id.state == 'posted':
                rec.move_id.button_draft()
            rec.state = 'draft'

    def action_post_due(self):
        today = fields.Date.today()
        self.filtered(lambda r: r.state == 'draft' and r.date <= today).action_post()

    def action_cancel(self):
        for rec in self.filtered(lambda r: r.state in ('draft', 'posted') and not r.is_initial):
            if rec.move_id:
                if rec.move_id.state == 'posted':
                    rec.move_id.button_draft()
                rec.move_id.unlink()
                rec.move_id = False
            rec.state = 'cancelled'

    def action_view_journal_entry(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.move_id.id,
            'view_mode': 'form',
        }

    def _create_recognition_entry(self):
        self.ensure_one()
        company = self.company_id.sudo()
        journal = (
            company.deferred_expense_journal_id
            if self.deferred_type == 'expense'
            else company.deferred_revenue_journal_id
        )

        if not journal:
            journal_type = _('Expense') if self.deferred_type == 'expense' else _('Revenue')
            raise UserError(_(
                'Please configure a Deferred %(type)s Journal in Accounting > Settings > Default Accounts.',
                type=journal_type,
            ))

        # Reverse direction for refunds (credit notes)
        is_refund = (
            self.invoice_line_id.move_id.move_type in ('in_refund', 'out_refund')
            if self.invoice_line_id else False
        )
        if self.deferred_type == 'expense':
            debit_account = self.deferred_account_id if is_refund else self.recognition_account_id
            credit_account = self.recognition_account_id if is_refund else self.deferred_account_id
        else:
            debit_account = self.recognition_account_id if is_refund else self.deferred_account_id
            credit_account = self.deferred_account_id if is_refund else self.recognition_account_id

        # amount_currency: positive on debit, negative on credit
        amt_currency = self.amount_currency or self.amount

        return self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': self.date,
            'ref': self.name,
            'company_id': company.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_account.id,
                    'debit': self.amount,
                    'credit': 0.0,
                    'name': self.name,
                    'partner_id': self.partner_id.id or False,
                    'currency_id': self.currency_id.id,
                    'amount_currency': amt_currency,
                    'analytic_distribution': self.analytic_distribution or False,
                }),
                (0, 0, {
                    'account_id': credit_account.id,
                    'debit': 0.0,
                    'credit': self.amount,
                    'name': self.name,
                    'partner_id': self.partner_id.id or False,
                    'currency_id': self.currency_id.id,
                    'amount_currency': -amt_currency,
                    'analytic_distribution': self.analytic_distribution or False,
                }),
            ],
        })
