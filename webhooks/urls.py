"""
URL configuration for production webhook endpoints
"""
from django.urls import path
from . import views

app_name = 'webhooks'

urlpatterns = [
    # Provider webhook endpoints
    path('withings/', views.withings_webhook_handler, name='withings-webhook'),
    path('fitbit/', views.fitbit_webhook_handler, name='fitbit-webhook'),

    # Health check and monitoring endpoints
    path('health/', views.webhook_health_check, name='webhook-health'),
    path('metrics/', views.webhook_metrics_endpoint, name='webhook-metrics'),

    # Debug endpoints
    path('debug/withings/subscriptions/', views.debug_withings_subscriptions, name='debug-withings-subscriptions'),
]