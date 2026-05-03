from odoo import models, fields


class ResCompany(models.Model):
    _inherit = 'res.company'

    vrs_deferred_enabled = fields.Boolean(
        string='Custom Deferred Recognition',
        default=False,
    )
    vrs_deferred_computation_method = fields.Selection(
        [('day', 'Days'), ('month', 'Months'), ('full_month', 'Full Months')],
        string='Based on',
        default='month',
        help='How to split the deferred amount across monthly periods for custom-account deferred lines.',
    )


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    vrs_deferred_enabled = fields.Boolean(
        related='company_id.vrs_deferred_enabled',
        readonly=False,
    )
    vrs_deferred_computation_method = fields.Selection(
        related='company_id.vrs_deferred_computation_method',
        readonly=False,
    )
