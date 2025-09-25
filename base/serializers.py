from rest_framework import serializers
from base.models import Provider, ProviderLink, EHRUser


# Unified validation methods and field definitions
class BaseHealthDataSerializer(serializers.Serializer):
    """Base serializer with common validation methods and field definitions"""

    # Common field definitions
    PROVIDER_CHOICES = ['withings', 'fitbit']

    @staticmethod
    def get_provider_field():
        """Get standardized provider choice field"""
        return serializers.ChoiceField(choices=BaseHealthDataSerializer.PROVIDER_CHOICES)

    @staticmethod
    def get_ehr_user_id_field():
        """Get standardized EHR user ID field with validation"""
        return serializers.CharField(max_length=100)

    @staticmethod
    def get_error_list_field():
        """Get standardized error list field"""
        return serializers.ListField(child=serializers.CharField(), required=False, default=list)

    @staticmethod
    def validate_ehr_user_id(value):
        """Unified EHR user ID validation"""
        import re
        if not re.match(r'^[a-zA-Z0-9_-]{3,100}$', value):
            raise serializers.ValidationError(
                "EHR user ID must be 3-100 characters, alphanumeric, hyphens, and underscores only"
            )
        return value


class ProviderSerializer(serializers.ModelSerializer):
    """Serializer for Provider model"""

    class Meta:
        model = Provider
        fields = ['id', 'name', 'provider_type', 'active']
        read_only_fields = ['id']


class ProviderLinkSerializer(serializers.ModelSerializer):
    """Serializer for ProviderLink model"""
    provider = ProviderSerializer(read_only=True)

    class Meta:
        model = ProviderLink
        fields = ['id', 'provider', 'external_user_id', 'extra_data', 'linked_at']
        read_only_fields = ['id', 'extra_data', 'linked_at']


class ProviderLinkingRequestSerializer(BaseHealthDataSerializer):
    """Serializer for provider linking requests"""
    ehr_user_id = BaseHealthDataSerializer.get_ehr_user_id_field()
    provider = BaseHealthDataSerializer.get_provider_field()

    def validate_ehr_user_id(self, value):
        """Validate EHR user ID format using unified validation"""
        return BaseHealthDataSerializer.validate_ehr_user_id(value)


class SyncStatusSerializer(BaseHealthDataSerializer):
    """Serializer for sync status responses"""
    ehr_user_id = serializers.CharField()
    provider = serializers.CharField()
    status = serializers.ChoiceField(choices=['pending', 'in_progress', 'completed', 'failed', 'no_recent_sync'])
    last_sync = serializers.DateTimeField(required=False, allow_null=True)
    next_sync = serializers.DateTimeField(required=False, allow_null=True)
    records_synced = serializers.IntegerField(required=False, allow_null=True)
    errors = BaseHealthDataSerializer.get_error_list_field()


class HealthDataCapabilitiesSerializer(serializers.Serializer):
    """Serializer for health data capabilities"""
    supported_providers = serializers.ListField(child=serializers.CharField())
    supported_data_types = serializers.ListField(child=serializers.CharField())
    webhook_endpoints = serializers.DictField()
    sync_frequencies = serializers.DictField()


class DeviceSyncRequestSerializer(BaseHealthDataSerializer):
    """Serializer for device sync requests"""
    ehr_user_id = BaseHealthDataSerializer.get_ehr_user_id_field()
    provider = BaseHealthDataSerializer.get_provider_field()

    def validate_ehr_user_id(self, value):
        """Validate EHR user ID format using unified validation"""
        return BaseHealthDataSerializer.validate_ehr_user_id(value)


class DeviceSyncResultSerializer(BaseHealthDataSerializer):
    """Serializer for device sync results"""
    message = serializers.CharField()
    sync_id = serializers.CharField()
    ehr_user_id = serializers.CharField()
    provider = serializers.CharField()
    devices_processed = serializers.IntegerField()
    associations_created = serializers.IntegerField()
    success = serializers.BooleanField()
    errors = BaseHealthDataSerializer.get_error_list_field()
