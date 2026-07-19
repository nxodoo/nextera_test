{
    "name": "Public Holiday Thursday Move",
    "version": "1.0",
    "summary": "Prompt users to move eligible public holidays to Thursday",
    "description": "Adds a confirmation flow that proposes moving eligible public holidays to Thursday based on the working schedule calendar.",
    "category": "Human Resources",
    "author": "Ahmed Tarek",
    "depends": ["hr_holidays", "hr_work_entry", "web"],
    "data": [],
    "assets": {
        "web.assets_backend": [
            "nx_public_holiday_thursday_move/static/src/js/public_holiday_move_dialog.js",
        ],
    },
    "installable": True,
    "application": False,
    "license": "LGPL-3",
}
