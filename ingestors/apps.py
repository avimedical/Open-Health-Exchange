from django.apps import AppConfig


class IngestorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "ingestors"
    label = "ingestors"

    def ready(self):
        """Import Huey tasks when the app is ready"""
        try:
            # Import all task modules to register them with Huey
            from . import (
                health_data_tasks,  # noqa: F401
                tasks,  # noqa: F401
            )
        except ImportError:
            # Tasks modules may not be available in all environments
            pass
