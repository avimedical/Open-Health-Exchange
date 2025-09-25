from django.apps import AppConfig


class MetricsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'metrics'

    def ready(self):
        """Initialize metrics collection when Django starts."""
        from . import collectors
        collectors.initialize_metrics()
