from rest_framework import serializers


class BloodPressureObservationSerializer(serializers.Serializer):
    resourceType = serializers.CharField(default="Observation")
    identifier = serializers.ListField(child=serializers.DictField(), required=False)
    status = serializers.CharField(default="final")
    category = serializers.ListField(child=serializers.DictField())
    code = serializers.DictField()
    subject = serializers.DictField()
    performer = serializers.ListField(child=serializers.DictField())
    issued = serializers.DateTimeField()
    device = serializers.DictField()
    effectiveDateTime = serializers.DateTimeField()
    component = serializers.ListField(child=serializers.DictField())


class ECGObservationSerializer(serializers.Serializer):
    resourceType = serializers.CharField(default="Observation")
    identifier = serializers.ListField(child=serializers.DictField(), required=False)
    status = serializers.CharField(default="final")
    category = serializers.ListField(child=serializers.DictField())
    code = serializers.DictField()
    subject = serializers.DictField()
    performer = serializers.ListField(child=serializers.DictField())
    issued = serializers.DateTimeField()
    device = serializers.DictField()
    effectiveDateTime = serializers.DateTimeField()
    valueAttachment = serializers.DictField()
    interpretation = serializers.ListField(child=serializers.DictField(), required=False)


class OxygenSaturationObservationSerializer(serializers.Serializer):
    resourceType = serializers.CharField(default="Observation")
    identifier = serializers.ListField(child=serializers.DictField(), required=False)
    status = serializers.CharField(default="final")
    category = serializers.ListField(child=serializers.DictField())
    code = serializers.DictField()
    subject = serializers.DictField()
    performer = serializers.ListField(child=serializers.DictField())
    issued = serializers.DateTimeField()
    device = serializers.DictField()
    effectiveDateTime = serializers.DateTimeField()
    valueQuantity = serializers.DictField()


class WeightObservationSerializer(serializers.Serializer):
    resourceType = serializers.CharField(default="Observation")
    identifier = serializers.ListField(child=serializers.DictField(), required=False)
    status = serializers.CharField(default="final")
    category = serializers.ListField(child=serializers.DictField())
    code = serializers.DictField()
    subject = serializers.DictField()
    performer = serializers.ListField(child=serializers.DictField())
    issued = serializers.DateTimeField()
    device = serializers.DictField()
    effectiveDateTime = serializers.DateTimeField()
    valueQuantity = serializers.DictField()
