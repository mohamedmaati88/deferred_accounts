from odoo.tests.common import TransactionCase


class TestAccountDeferred(TransactionCase):

    def test_module_installed(self):
        self.assertTrue(
            self.env['ir.module.module'].search([('name', '=', 'deferred_accounts'), ('state', '=', 'installed')]),
            "deferred_accounts module should be installed",
        )

    def test_company_fields_exist(self):
        company = self.env.company
        self.assertFalse(company.vrs_deferred_enabled)
        self.assertEqual(company.vrs_deferred_computation_method, 'month')

    def test_move_fields_exist(self):
        move = self.env['account.move'].new({'move_type': 'entry'})
        self.assertFalse(move.vrs_is_deferred)
        self.assertEqual(move.vrs_deferred_line_count, 0)
