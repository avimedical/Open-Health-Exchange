import logging
from django.http import JsonResponse, HttpResponseRedirect
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.renderers import JSONRenderer
from django.urls import reverse
from social_django.utils import load_backend, load_strategy
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.contrib.auth import get_user_model
from django.core.cache import cache
import json
from mozilla_django_oidc.contrib.drf import OIDCAuthentication
from rest_framework import exceptions

from base.models import Provider, ProviderLink
from base.serializers import ProviderSerializer


logger = logging.getLogger(__name__)


class ProviderViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows Providers to be viewed and edited.
    """

    permission_classes = [IsAuthenticated]
    queryset = Provider.objects.all()
    serializer_class = ProviderSerializer
    default_renderer_classes = [JSONRenderer]