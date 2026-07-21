{
    'name': 'HR Career & Development',
    'version': '1.0',
    'summary': 'Track employee job history, education, and work experience',
    'category': 'Human Resources',
    'author': 'Ahmed Tarek',
    'depends': ['hr', 'hr_skills'],
    'data': [
        'security/ir.model.access.csv',
        'views/hr_employee_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'nx_hr_career_development/static/src/js/section_toggle_widget.js',
            'nx_hr_career_development/static/src/xml/section_toggle_widget.xml',
            'nx_hr_career_development/static/src/scss/section_toggle.scss',
        ],
    },
    'application': False,
    'installable': True,
    'license': 'LGPL-3',
}
