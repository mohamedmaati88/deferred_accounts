from odoo import models, fields, api, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    vrs_deferred_enabled = fields.Boolean(
        related='company_id.vrs_deferred_enabled',
        string='Deferred Module Enabled',
    )
    vrs_is_deferred = fields.Boolean(
        string='Custom Deferred',
        default=False,
        copy=False,
        help='Enable custom deferred accounting for lines on this entry.',
    )
    vrs_deferred_line_count = fields.Integer(
        compute='_compute_vrs_deferred_line_count',
        string='Deferred Schedule Entries',
    )

    @api.depends('line_ids.vrs_deferred_line_ids')
    def _compute_vrs_deferred_line_count(self):
        for move in self:
            move.vrs_deferred_line_count = sum(
                len(l.vrs_deferred_line_ids) for l in move.line_ids
            )

    def action_view_deferred_schedule(self):
        self.ensure_one()
        line_ids = self.line_ids.mapped('vrs_deferred_line_ids').ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recognition Schedule'),
            'res_model': 'account.deferred.line',
            'view_mode': 'list,form',
            'domain': [('id', 'in', line_ids)],
        }

    @api.onchange('vrs_is_deferred')
    def _onchange_vrs_is_deferred(self):
        if self.vrs_is_deferred:
            self.line_ids.write({
                'deferred_start_date': False,
                'deferred_end_date': False,
            })
        else:
            self.line_ids.write({
                'vrs_deferred_account_id': False,
                'vrs_deferred_start_date': False,
                'vrs_deferred_end_date': False,
            })

    def action_post(self):
        for move in self.filtered(lambda m: m.vrs_is_deferred):
            lines_with_std = move.line_ids.filtered(
                lambda l: l.deferred_start_date or l.deferred_end_date
            )
            if lines_with_std:
                lines_with_std.write({'deferred_start_date': False, 'deferred_end_date': False})
        result = super().action_post()
        for move in self.filtered(lambda m: m.vrs_is_deferred):
            for line in move.line_ids.filtered(
                lambda l: l.vrs_deferred_account_id
                and l.vrs_deferred_start_date
                and l.vrs_deferred_end_date
                and not l.vrs_deferred_line_ids
            ):
                line._create_deferral_entry()
                line._create_deferred_schedule()
        return result

    def _vrs_check_lock_dates(self, deferred_lines):
        """Raise if any recognition entry falls within a locked fiscal period."""
        company = self.company_id
        lock_date = getattr(company, 'fiscalyear_lock_date', False)
        if not lock_date:
            return
        for dl in deferred_lines.filtered(lambda l: l.move_id):
            entry_date = dl.move_id.date
            if entry_date and entry_date <= lock_date:
                raise UserError(_(
                    'Cannot cancel/reset recognition entry "%s" dated %s: '
                    'the fiscal period is locked until %s.\n'
                    'Contact your accountant to unlock the period first.',
                    dl.move_id.name or dl.name,
                    entry_date,
                    lock_date,
                ))

    def _vrs_clear_deferred_lines(self):
        for move in self:
            all_dl = move.line_ids.mapped('vrs_deferred_line_ids')
            if all_dl:
                move._vrs_check_lock_dates(all_dl)
                for dl in all_dl.filtered(lambda l: l.move_id):
                    entry = dl.move_id
                    if entry.state == 'posted':
                        entry.button_draft()
                    entry.unlink()
                all_dl.sudo().unlink()

    def _vrs_cancel_standard_deferred(self):
        """Cancel any standard Odoo deferred amortization entries linked to these moves."""
        std_field = 'deferred_move_ids'
        if std_field not in self.env['account.move']._fields:
            return
        for move in self:
            std_entries = move[std_field].filtered(lambda m: m.state != 'cancel')
            if std_entries:
                std_entries.filtered(lambda m: m.state == 'posted').button_draft()
                std_entries.unlink()

    def button_draft(self):
        self._vrs_cancel_standard_deferred()
        self._vrs_clear_deferred_lines()
        return super().button_draft()

    def button_cancel(self):
        self._vrs_cancel_standard_deferred()
        self._vrs_clear_deferred_lines()
        return super().button_cancel()
