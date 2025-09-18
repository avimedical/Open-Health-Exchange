from huey import RedisHuey
from open_health_exchange.settings import HUEY_CONFIG

huey = RedisHuey(**HUEY_CONFIG)


@huey.task()
def fetch_withings_data(provider_credential_id):
    """
    Huey task to fetch data from Withings API.
    """
    from devices.models import ProviderCredential
    credential = ProviderCredential.objects.get(id=provider_credential_id)

    from withings_api import WithingsClient

    client = WithingsClient(
        access_token=credential.access_token,
        refresh_token=credential.refresh_token,
        client_id=credential.provider.client_id,
        client_secret=credential.provider.client_secret,
        userid=credential.external_user_id
    )

    # Fetch devices information
    try:
        devices = client.get_devices()
        print(f"Successfully fetched Withings devices for credential: {credential.id}")

        from devices.serializers import FHIRDeviceDefinitionSerializer, FHIRDeviceSerializer
        from devices.models import DeviceConfiguration

        for device in devices:
            # Create FHIR DeviceDefinition resource
            device_definition_data = {'placeholder_field': 'WithingsDeviceDefinition'}  # Placeholder data
            fhir_device_definition_serializer = FHIRDeviceDefinitionSerializer(data=device_definition_data)
            if fhir_device_definition_serializer.is_valid():
                fhir_device_definition_serializer.save()
                fhir_device_definition_id = "DeviceDefinition/" + "temp_id_123"  # TODO: Get actual FHIR resource ID

                # Create FHIR Device resource
                fhir_device_serializer = FHIRDeviceSerializer(data={'placeholder_field': 'WithingsDevice'})  # Placeholder data
                if fhir_device_serializer.is_valid():
                    fhir_device_serializer.save()
                    fhir_device_id = "Device/" + "temp_id_456"  # TODO: Get actual FHIR resource ID

                    # Update DeviceConfiguration with FHIR resource IDs
                    device_configuration = DeviceConfiguration.objects.get(provider_credential=credential)
                    device_configuration.fhir_device_definition_id = fhir_device_definition_id
                    device_configuration.fhir_device_id = fhir_device_id
                    device_configuration.save()
                    message = "FHIR Device and DeviceDefinition resources created and DeviceConfiguration updated for credential:" # Shortened message
                    print(f"{message} {credential.id}")
                else:
                    print(f"Error serializing FHIR Device resource: {fhir_device_serializer.errors}")
            else:
                print(f"Error serializing FHIR DeviceDefinition resource: {fhir_device_definition_serializer.errors}")
        print(devices)
    except Exception as e:
        print(f"Error fetching Withings data for credential {credential.id}: {e}")
        pass

@huey.task()
def test_task():
    """
    Simple test Huey task.
    """
    print("Test Huey task executed successfully!")

    
    
@huey.task()
def fetch_fitbit_data(provider_credential_id):
    """
    Huey task to fetch data from Fitbit API.
    """
    from ingestors.models import ProviderCredential
    credential = ProviderCredential.objects.get(id=provider_credential_id)

    import fitbit

    client = fitbit.Fitbit(
        credential.provider.client_id,
        credential.provider.client_secret,
        oauth2=True,
        access_token=credential.access_token,
        refresh_token=credential.refresh_token,
        refresh_cb=lambda token: print("Token refreshed!")  # TODO: Implement token refresh callback
    )

    # Fetch activities (example)
    try:
        activities = client.activities()
        print(f"Successfully fetched Fitbit activities for credential: {credential.id}")
        # TODO: Process and transform activities data
        print(activities)
    except Exception as e:
        print(f"Error fetching Fitbit data for credential {credential.id}: {e}")
        pass

    # Fetch device information for Fitbit
    try:
        user_profile = client.user_profile_get()
        if user_profile and 'user' in user_profile:
            device_data_list = user_profile['user'].get('devices', [])
            print(f"Successfully fetched Fitbit devices for credential: {credential.id}")

            from devices.serializers import FHIRDeviceDefinitionSerializer, FHIRDeviceSerializer
            from devices.models import DeviceConfiguration

            for device_data in device_data_list:  # device_data is each element in device_data_list
                # Create FHIR DeviceDefinition resource
                fhir_device_definition_serializer = FHIRDeviceDefinitionSerializer(data={
                    'identifier': device_data.get('id'),  # Using Fitbit device ID as identifier
                    'manufacturer': device_data.get('manufacturer'),
                    'model_number': device_data.get('deviceVersion'),  # Using deviceVersion as modelNumber
                    'type': device_data.get('type')  # Device type (e.g., TRACKER, SCALE)
                })
                if fhir_device_definition_serializer.is_valid():
                    fhir_device_definition_serializer.save()
                    fhir_device_definition_id = "DeviceDefinition/fitbit-" + str(device_data.get('id'))  # TODO: Get actual FHIR resource ID

                    # Create FHIR Device resource (minimal placeholder for now)
                    fhir_device_serializer = FHIRDeviceSerializer(data={'placeholder_field': 'FitbitDevice'})  # Placeholder data
                    if fhir_device_serializer.is_valid():
                        fhir_device_serializer.save()
                        fhir_device_id = "Device/fitbit-" + str(device_data.get('id'))  # TODO: Get actual FHIR resource ID

                        # Update DeviceConfiguration with FHIR resource IDs
                        device_configuration = DeviceConfiguration.objects.get(provider_credential=credential)
                        device_configuration.fhir_device_definition_id = fhir_device_definition_id
                        device_configuration.fhir_device_id = fhir_device_id
                        device_configuration.save()
                        message = ("FHIR Device and DeviceDefinition resources created and "
                                   "DeviceConfiguration updated for Fitbit credential:")
                        print(f"{message} {credential.id}")
                    else:
                        print(f"Error serializing FHIR Device resource (Fitbit): {fhir_device_serializer.errors}")
                else:
                    print(f"Error serializing FHIR DeviceDefinition resource (Fitbit): {fhir_device_definition_serializer.errors}")


    except Exception as e:
        print(f"Error fetching Fitbit devices for credential {credential.id}: {e}")
        pass
