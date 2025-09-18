app_name = "helpdesk"
app_title = "Helpdesk"
app_publisher = "Frappe Technologies"
app_description = "Customer Service Software"
app_icon = "octicon octicon-file-directory"
app_color = "grey"
app_email = "hello@frappe.io"
app_license = "AGPLv3"


add_to_apps_screen = [
    {
        "name": "helpdesk",
        "logo": "/assets/helpdesk/desk/favicon.svg",
        "title": "Helpdesk",
        "route": "/helpdesk",
        "has_permission": "helpdesk.api.permission.has_app_permission",
    }
]


after_install = "helpdesk.setup.install.after_install"
after_migrate = [
    "helpdesk.search.build_index_in_background",
    "helpdesk.search.download_corpus",
]

scheduler_events = {
    "all": [
        "helpdesk.search.build_index_if_not_exists",
        "helpdesk.search.download_corpus",
    ],
    "daily": [
        "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.close_tickets_after_n_days"
    ],
    "hourly": [
        "helpdesk.api.license.verify_and_update"

    ],
}

website_route_rules = [
    {
        "from_route": "/helpdesk/<path:app_path>",
        "to_route": "helpdesk",
    },
]

doc_events = {
    "Contact": {
       "before_insert": [
        "helpdesk.overrides.contact.before_insert",
        "helpdesk.api.ticket_hooks.before_insert_set_license_flag",
     ]
    },
    "Assignment Rule": {
        "on_trash": "helpdesk.extends.assignment_rule.on_assignment_rule_trash",
    },      
    
}

has_permission = {
    "HD Ticket": "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.has_permission",
    "Communication": "helpdesk.overrides.communication.has_permission",
}

permission_query_conditions = {
    "HD Ticket": "helpdesk.helpdesk.doctype.hd_ticket.hd_ticket.permission_query",
    "Communication": "helpdesk.overrides.communication.get_permission_query_conditions",
}

# DocType Class
# ---------------
# Override standard doctype classes
override_doctype_class = {
    "Email Account": "helpdesk.overrides.email_account.CustomEmailAccount",
}

ignore_links_on_delete = [
    "HD Notification",
    "HD Ticket Comment",
]

# 5) Desk tarafına global CSS enjekte
app_include_css = [
    "/assets/helpdesk/css/fullwidth-list.css",
]


# --- Fixtures: taşıyacağımız kayıtlar ---
fixtures = [
    # Kurduğumuz yönetim rolü
    {"dt": "Role", "filters": [["role_name", "in", ["AI Admin"]]]},

    # N8n’e giden webhook’umuz (adı sizde farklıysa güncelleyin)
    {"dt": "Webhook", "filters": [["name", "in", ["Ticket Summary"]]]},
    {"dt": "AI Interaction Log", "filters": [["name", "in", ["AI Interaction Log"]]]},
    {"dt": "HD Ticket", "filters": [["name", "in", ["HD Ticket"]]]},
    {"dt": "HelpdeskAI Settings", "filters": [["name", "in", ["HelpdeskAI Settings"]]]},
    {"dt": "Knowledge Base Update Request", "filters": [["name", "in", ["Knowledge Base Update Request"]]]},
    {"dt": "License Audit Log", "filters": [["name", "in", ["License Audit Log"]]]},
    {"dt": "Problem Ticket", "filters": [["name", "in", ["Problem Ticket"]]]},

    # App içindeki özelleştirmeler (varsa) – gürültüyü azaltmak için Helpdesk modülüyle sınırlandırdık
    {"dt": "Custom Field", "filters": [["module", "=", "Helpdesk"]]},
    {"dt": "Property Setter", "filters": [["module", "=", "Helpdesk"]]},
    {"dt": "Client Script", "filters": [["module", "=", "Helpdesk"]]},
    {"dt": "Server Script", "filters": [["module", "=", "Helpdesk"]]},
]



# setup wizard
# setup_wizard_requires = "assets/helpdesk/js/setup_wizard.js"
# setup_wizard_stages = "helpdesk.setup.setup_wizard.get_setup_stages"
setup_wizard_complete = "helpdesk.setup.setup_wizard.setup_complete"


# Testing
# ---------------

before_tests = "helpdesk.test_utils.before_tests"
