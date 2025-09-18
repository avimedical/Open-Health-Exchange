# Active Context: Health Data Sync Micro-service

## Current Work Focus
Implementing FHIR Device creation and Device Management API endpoints.

## Recent Changes
- Created `projectbrief.md`, `productContext.md`, `systemPatterns.md`, `techContext.md`, and `progress.md` files to setup memory bank.
- Renamed Django apps: `devices` to `base`, `fetch_data` to `ingestors`, `transform_data` to `transformers`, and `push_fhir_data` to `publishers`.
- Updated `INSTALLED_APPS` in `open_health_exchange/settings.py` to reflect app renames.
- Renamed `ProviderCredentials` model to `ProviderLink` (already done).
- Removed `DeviceConfiguration` model and related ViewSets (`FHIRDeviceDefinitionViewSet`, `FHIRDeviceViewSet`).
- Integrated Huey and Redis for task queue management.
- Integrated Black and Flake8 code formatting and linting.
- Added `python-social-auth` and `fhirpy` dependencies, replacing `django-oauth-toolkit`.
- Configured `python-social-auth` in `settings.py`.
- Defined `Provider` and `ProviderLink` models in `base` app.
- Implemented initial API endpoints and serializers for `Provider` and `ProviderLink` in `base` app.
- Removed ViewSets for `DeviceConfiguration` and `ProviderLink`.
- Implemented initial OAuth2 flow initiation and callback handling in `ProviderLinkViewSet` in `base/views.py`.
- Moved user association logic to custom pipelines in `base/pipeline.py`.
- Deleted custom functions from `ProviderViewSet` in `base/views.py`.
- Updated URLs in `base/urls.py` to use provider name in path and new URL schema `/api/<module>/<endpoint>/*`:
  - `/api/base/provider-links/<str:provider_type>/initiate_oauth2/`
  - `/api/base/provider-links/<str:provider_type>/oauth2_callback/`
  - `/api/base/provider-links/<str:provider_type>/create_fhir_device/`
- Updated root URLconf in `open_health_exchange/urls.py` to include base URLs under `/api/base/` path.
- Configured API versioning to use AcceptHeaderVersioning.
- Social login works for Withings and Fitbit.

## Next Steps
1. **FHIR Device Creation and Device Management:**
    - Implement logic to retrieve device information from Withings and Fitbit APIs and create FHIR Device and DeviceDefinition resources.
    - Implement API endpoints for device management and data synchronization.
2. **Define initial tasks for data fetching in the `ingestors` app using Huey.**
    - Start with Withings and Fitbit.
3. **Data transformation and FHIR push logic in respective apps.**
4. **Metrics collection and Prometheus integration.**
5. **Authentication implementation (OAuth2, JWT).**
6. **Kubernetes deployment configurations.**
7. **UI development (separate project).**
8. **Testing (unit, integration, end-to-end).**
9. **Documentation (API, development, deployment).**

## Active Decisions and Considerations
- **Task Queue Choice:** Huey with PriorityQueue is confirmed.
- **Code Formatting & Linting:** Black and Flake8 are integrated.
- **OAuth2 Library:** Using `python-social-auth`.
- **FHIR Client Library:** Using `fhirpy`.
- **Device Mapping:** Need to define mapping strategy for device data to FHIR resources.
- **Error Handling and Logging:** Need to implement robust error handling and logging.
- **Security:** Securely store and manage API credentials and OAuth2 tokens.

## Questions for User
- None at this time.
