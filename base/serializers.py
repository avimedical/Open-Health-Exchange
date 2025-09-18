from rest_framework import serializers
from base.models import Provider


class ProviderSerializer(serializers.ModelSerializer):

    class Meta:
        model = Provider
        fields = [
            'id', 'name', 'provider_type', 'active'
        ]


class FHIRDeviceDefinitionSerializer(serializers.Serializer):
    """
    Serializer for FHIR DeviceDefinition resource.
    """
    resource_type = serializers.CharField(default="DeviceDefinition")
    identifier = serializers.CharField(required=False)  # FHIR Identifier type is more complex, using string for now
    manufacturer = serializers.CharField(required=False)
    model_number = serializers.CharField(required=False, source='modelNumber')  # Map to FHIR modelNumber
    type = serializers.CharField(required=False)  # FHIR CodeableConcept type is more complex, using string for now
    # Define fields based on FHIR DeviceDefinition resource
    # ... more fields to be added


class FHIRDeviceSerializer(serializers.Serializer):
    """
    Placeholder serializer for FHIR Device resource.
    """

    resource_type = serializers.CharField(default="Device")
    # Define fields based on FHIR Device resource
    # For now, just include a placeholder field
    placeholder_field = serializers.CharField(required=False)
