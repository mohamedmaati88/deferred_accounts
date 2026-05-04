import calendar

from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from dateutil.relativedelta import relativedelta

# Account types that cannot be used as deferred accounts
_FORBIDDEN_DEFERRED_ACCOUNT_TYPES = frozenset((
    'asset_receivable',
    'liability_payable',
    'asset_cash',
))


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    vrs_deferred_account_id = fields.Many2one(
        'account.account',
        string='Deferred Account',
        domain="[('account_type', 'in', ['asset_current', 'asset_non_current', 'liability_current', 'liability_non_current'])]",
        copy=False,
    )
    # Independent date fields — never touch deferred_start_date / deferred_end_date.
    vrs_deferred_start_date = fields.Date(string='Def. Start', copy=False)
    vrs_deferred_end_date = fields.Date(string='Def. End', copy=False)

    vrs_deferred_line_ids = fields.One2many(
        'account.deferred.line',
        'invoice_line_id',
        string='Recognition Schedule',
    )
    vrs_deferred_line_count = fields.Integer(
        compute='_compute_vrs_deferred_line_count',
        string='Recognition Entries',
    )

    @api.depends('vrs_deferred_line_ids')
    def _compute_vrs_deferred_line_count(self):
        for rec in self:
            rec.vrs_deferred_line_count = len(rec.vrs_deferred_line_ids)

    @api.constrains('vrs_deferred_start_date', 'vrs_deferred_end_date')
    def _check_deferred_dates(self):
        for rec in self:
            start = rec.vrs_deferred_start_date
            end = rec.vrs_deferred_end_date
            if start and end and start >= end:
                raise ValidationError(_(
                    'Deferral start date (%s) must be before end date (%s).',
                    start, end,
                ))

    @api.constrains('vrs_deferred_account_id')
    def _check_deferred_account_type(self):
        for rec in self:
            acc = rec.vrs_deferred_account_id
            if acc and acc.account_type in _FORBIDDEN_DEFERRED_ACCOUNT_TYPES:
                raise ValidationError(_(
                    'Account "%s" cannot be used as a deferred account '
                    '(Receivable, Payable, and Liquidity accounts are not allowed).',
                    acc.display_name,
                ))

    def action_view_deferred_schedule_line(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recognition Schedule'),
            'res_model': 'account.deferred.line',
            'view_mode': 'list,form',
            'domain': [('invoice_line_id', '=', self.id)],
        }

    def _get_deferred_type(self):
        self.ensure_one()
        if self.move_id.move_type in ('in_invoice', 'in_refund'):
            return 'expense'
        if self.move_id.move_type in ('out_invoice', 'out_refund'):
            return 'revenue'
        # For journal entries: debit lines → expense, credit lines → revenue
        return 'expense' if self.balance >= 0 else 'revenue'

    def _get_deferred_journal(self, deferred_type):
        company = self.move_id.company_id.sudo()
        return (
            company.deferred_expense_journal_id
            if deferred_type == 'expense'
            else company.deferred_revenue_journal_id
        )

    def _create_deferral_entry(self):
        self.ensure_one()
        company = self.move_id.company_id.sudo()
        deferred_type = self._get_deferred_type()
        deferred_account = self.vrs_deferred_account_id
        journal = self._get_deferred_journal(deferred_type)

        if not journal:
            journal_type = _('Expense') if deferred_type == 'expense' else _('Revenue')
            raise UserError(_(
                'Please configure a Deferred %(type)s Journal in Accounting > Settings > Default Accounts.',
                type=journal_type,
            ))

        recognition_account = self.account_id
        amount = abs(self.balance)
        amount_currency = abs(self.amount_currency) if self.amount_currency else amount
        invoice_date = self.move_id.invoice_date or fields.Date.today()
        partner = self.move_id.partner_id
        ref = _('Deferral: %(move)s / %(line)s') % {
            'move': self.move_id.name,
            'line': self.name or (self.product_id.name if self.product_id else ''),
        }

        # Reverse debit/credit direction for refunds (credit notes)
        is_refund = self.move_id.move_type in ('in_refund', 'out_refund')
        if deferred_type == 'expense':
            if is_refund:
                debit_account, credit_account = recognition_account, deferred_account
            else:
                debit_account, credit_account = deferred_account, recognition_account
        else:
            if is_refund:
                debit_account, credit_account = deferred_account, recognition_account
            else:
                debit_account, credit_account = recognition_account, deferred_account

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': journal.id,
            'date': invoice_date,
            'ref': ref,
            'company_id': company.id,
            'currency_id': self.currency_id.id,
            'line_ids': [
                (0, 0, {
                    'account_id': debit_account.id,
                    'debit': amount,
                    'credit': 0.0,
                    'name': ref,
                    'partner_id': partner.id or False,
                    'currency_id': self.currency_id.id,
                    'amount_currency': amount_currency,
                    'analytic_distribution': self.analytic_distribution or False,
                }),
                (0, 0, {
                    'account_id': credit_account.id,
                    'debit': 0.0,
                    'credit': amount,
                    'name': ref,
                    'partner_id': partner.id or False,
                    'currency_id': self.currency_id.id,
                    'amount_currency': -amount_currency,
                    'analytic_distribution': self.analytic_distribution or False,
                }),
            ],
        })
        move.action_post()

        self.env['account.deferred.line'].sudo().create({
            'name': ref,
            'is_initial': True,
            'invoice_line_id': self.id,
            'deferred_type': deferred_type,
            'date': invoice_date,
            'amount': amount,
            'amount_currency': amount_currency,
            'partner_id': partner.id or False,
            'analytic_distribution': self.analytic_distribution or False,
            'recognition_account_id': recognition_account.id,
            'deferred_account_id': deferred_account.id,
            'move_id': move.id,
            'state': 'posted',
        })
        return move

    def _compute_deferred_periods(self, start, end, amount):
        """Split amount across monthly periods using the company's Based on method."""
        company = self.move_id.company_id.sudo()
        method = company.vrs_deferred_computation_method or 'month'

        periods = []
        current = start.replace(day=1)
        while current <= end:
            period_start = max(start, current)
            next_month = current + relativedelta(months=1)
            period_end = min(end, next_month - relativedelta(days=1))
            period_days = (period_end - period_start).days + 1
            periods.append({
                'date': period_end,
                'period_start': period_start,
                'period_end': period_end,
                'period_days': period_days,
            })
            current = next_month

        if method == 'month':
            nb = len(periods)
            base = round(amount / nb, 2)
            for p in periods:
                p['amount'] = base
        elif method == 'full_month':
            weights = []
            for p in periods:
                days_in_month = calendar.monthrange(p['period_start'].year,
                                                    p['period_start'].month)[1]
                weights.append(p['period_days'] / days_in_month)
            total_weight = sum(weights)
            for p, w in zip(periods, weights):
                p['amount'] = round(amount * w / total_weight, 2)
        else:  # 'day'
            total_days = (end - start).days + 1
            for p in periods:
                p['amount'] = round(amount * p['period_days'] / total_days, 2)

        # Fix rounding difference on the last period
        diff = amount - sum(p['amount'] for p in periods)
        if periods and diff:
            periods[-1]['amount'] = round(periods[-1]['amount'] + diff, 2)

        return periods

    def _create_deferred_schedule(self):
        self.ensure_one()
        start = self.vrs_deferred_start_date
        end = self.vrs_deferred_end_date
        amount = abs(self.balance)
        amount_currency_total = abs(self.amount_currency) if self.amount_currency else amount
        deferred_type = self._get_deferred_type()
        recognition_account = self.account_id
        deferred_account = self.vrs_deferred_account_id
        partner = self.move_id.partner_id

        periods = self._compute_deferred_periods(start, end, amount)

        # Distribute amount_currency proportionally across periods
        for p in periods:
            p['amount_currency'] = (
                round(amount_currency_total * p['amount'] / amount, 2)
                if amount else 0.0
            )
        # Fix currency rounding on last period
        diff_currency = amount_currency_total - sum(p['amount_currency'] for p in periods)
        if periods and diff_currency:
            periods[-1]['amount_currency'] = round(periods[-1]['amount_currency'] + diff_currency, 2)

        today = fields.Date.today()
        invoice_ref = self.move_id.name or self.move_id.ref or _('Invoice')
        total = len(periods)
        lines = self.env['account.deferred.line'].sudo().create([
            {
                'name': _('%(ref)s - Recognition %(n)d/%(total)d') % {
                    'ref': invoice_ref, 'n': i + 1, 'total': total,
                },
                'invoice_line_id': self.id,
                'deferred_type': deferred_type,
                'date': p['date'],
                'amount': p['amount'],
                'amount_currency': p['amount_currency'],
                'partner_id': partner.id or False,
                'analytic_distribution': self.analytic_distribution or False,
                'recognition_account_id': recognition_account.id,
                'deferred_account_id': deferred_account.id,
                'state': 'draft',
            }
            for i, p in enumerate(periods)
        ])
        for line in lines:
            move = line._create_recognition_entry()
            line.move_id = move
            if line.date <= today:
                move.action_post()
                line.state = 'posted'
