{
    'name': 'Deferred Revenue & Expense Control',
    'version': '19.0.3.7.0',
    'category': 'Accounting/Accounting',
    'summary': 'Set deferred accounts per invoice line or journal entry — override company defaults with full flexibility',
    'description': """
Deferred Revenue & Expense Control
====================================
Advanced Deferral Management for Odoo

Gain full control over deferred revenue and expense recognition by selecting
deferred accounts directly on invoices and journal entries.

Key Features
-------------
- Set deferred accounts at invoice level (vendor bills & customer invoices)
- Set deferred accounts at journal entry level
- Override the default deferred account per line when needed
- Support both revenue and expense deferral flows
- Generate a clear monthly recognition schedule automatically on posting
- Past periods posted immediately, future periods kept in draft
- Three distribution methods: Days, Months, Full Months
- Smart button for instant access to the full recognition schedule
- Reset to draft / re-post recognition entries individually
- Cancelling or resetting the source entry clears all related entries

Configuration
--------------
Accounting → Settings → Custom Deferred Recognition
    """,
    'author': 'Mohamed Maati',
    'images': ['static/description/banner.png'],
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/account_deferred_line_views.xml',
        'views/account_move_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
