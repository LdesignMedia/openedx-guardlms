from django.apps import AppConfig


class GuardLMSConfig(AppConfig):
    name = "guardlms_openedx"
    verbose_name = "GuardLMS"
    default_auto_field = "django.db.models.BigAutoField"
    plugin_app = {
        "url_config": {
            service: {"namespace": "guardlms", "regex": r"^guardlms/", "relative_path": "urls"}
            for service in ("lms.djangoapp", "cms.djangoapp")
        },
        "settings_config": {
            service: {"common": {"relative_path": "settings.common"}}
            for service in ("lms.djangoapp", "cms.djangoapp")
        },
    }

    def ready(self):
        from . import telemetry  # noqa: F401; register Celery's failure signal
