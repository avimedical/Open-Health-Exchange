from django.apps import AppConfig


class BaseConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "base"
    label = "base"

    def ready(self):
        # Import signals to register signal handlers
        import base.signals  # noqa: F401
