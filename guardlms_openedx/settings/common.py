def plugin_settings(settings):
    settings.GUARDLMS_API_URL = "https://api.guardlms.com"
    settings.GUARDLMS_DASHBOARD_URL = "https://dashboard.guardlms.com"
    settings.GUARDLMS_ENCRYPTION_KEY = ""
    settings.GUARDLMS_MFE_MANIFEST = "/openedx/guardlms/npm-inventory.json"
    settings.GUARDLMS_BROWSER_ORIGINS = []
    settings.MIDDLEWARE = list(settings.MIDDLEWARE) + ["guardlms_openedx.middleware.MonitoringMiddleware"]
    schedule = dict(getattr(settings, "CELERYBEAT_SCHEDULE", {}))
    schedule["guardlms-inventory"] = {"task": "guardlms_openedx.tasks.report_due", "schedule": 60.0}
    settings.CELERYBEAT_SCHEDULE = schedule
