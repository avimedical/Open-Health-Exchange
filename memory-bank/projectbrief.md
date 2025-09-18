# Project Brief: Health Data Sync Micro-service

## Goal
Develop a Django-based micro-service to synchronize health data from third-party providers (Withings, Fitbit, Omron, Beurer) to an Electronic Health Record (EHR) system based on FHIR R5.

## Functionality
- **Data Synchronization:** Fetch health data from various providers and map it to FHIR R5 resources.
- **Configuration:** Allow users to configure credentials for both third-party providers and the EHR system.
- **Data Mapping:** Implement configurable data mapping between provider data models and FHIR R5.
- **Scalability:** Design for horizontal scaling of worker components to handle varying data volumes.
- **Monitoring:** Expose metrics for monitoring and integration with Prometheus.
- **Background Sync:** Implement cron jobs for nightly data synchronization to capture missing data.
- **Security:** Implement OAuth2 or JWT for authentication against the FHIR server and utilize provider-specific authentication mechanisms (preferably OAuth2) for third-party APIs.
- **No Data Storage:** The micro-service should not store any health data itself, only configuration and mapping details.

## Architecture
- **Django-based:** Utilize Django framework for development.
- **Multi-App Structure:** Organize functionality into separate Django apps:
    - `fetch_data`: For retrieving data from third-party providers.
    - `transform_data`: For mapping and transforming data to FHIR R5.
    - `push_fhir_data`: For pushing data to the FHIR server with duplicate checking.
    - `device_management`: For managing user devices and provider connections.
    - `metrics`: For exposing application metrics to Prometheus.
- **REST API:** Expose RESTful APIs using Django REST Framework.
- **Database:** PostgreSQL for primary data storage (configuration, mappings).
- **Task Queue:** Redis for managing asynchronous tasks and queues.
- **Application Server:** Hypercorn.
- **Deployment:** Kubernetes.

## Stack
- Django
- Django REST Framework
- Hypercorn
- PostgreSQL
- Redis
- Prometheus

## Authentication
- **Third-Party Providers:** OAuth2 preferred, provider-specific methods as needed.
- **FHIR Server:** OAuth2 or JWT.

## Deployment
- Kubernetes deployment for scalability and resilience.
- Independent UI deployment.
- Horizontally scalable workers based on queue metrics.
- Prometheus for metrics monitoring.
- Cron jobs for nightly data sync.
