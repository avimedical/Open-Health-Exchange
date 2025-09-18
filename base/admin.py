from django.contrib import admin
from base.models import EHRUser, Provider

admin.site.register(Provider)
admin.site.register(EHRUser)
