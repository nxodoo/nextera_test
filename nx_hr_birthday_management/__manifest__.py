{
    'name': 'HR Birthday Management',
    'version': '18.0.1.0.0',
    'summary': 'Manage employee birthday reminders and greetings',
    'category': 'Human Resources/Employees',
    'author': 'Ahmed Tarek',
    'license': 'LGPL-3',
    'depends': ['hr', 'mail'],
    'data': [
        'data/mail_template_data.xml',
        'data/ir_cron_data.xml',
        'views/res_config_settings_views.xml',
    ],
    'installable': True,
    'application': False,
}
