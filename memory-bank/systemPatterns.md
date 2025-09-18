# System Patterns: Health Data Sync Micro-service

## System Architecture
```mermaid
graph LR
    subgraph Third-Party Providers
        direction TB
        Withings
        Fitbit
        Omron
        Beurer
    end
    
    subgraph Health Data Sync Micro-service
        direction TB
        subgraph Django Apps
            fetch_data
            transform_data
            push_fhir_data
            device_management
            metrics
        end
        REST_API[REST API (DRF)]
        PostgreSQL[PostgreSQL DB]
        Redis[Redis Queue]
        Prometheus[Prometheus Metrics]
        Hypercorn[Hypercorn Server]
        Cron_Jobs[Cron Jobs]
    end
    
    subgraph EHR System (FHIR R5)
        FHIR_API[FHIR API]
    end

    Third-Party Providers --> fetch_data
    fetch_data --> transform_data
    transform_data --> push_fhir_data
    push_fhir_data --> FHIR_API
    device_management --> Withings & Fitbit & Omron & Beurer
    REST_API --> device_management
    REST_API --> fetch_data
    REST_API --> transform_data
    REST_API --> push_fhir_data
    fetch_data --> Redis
    transform_data --> Redis
    push_fhir_data --> Redis
    metrics --> Prometheus
    Hypercorn --> Django Apps
    Django Apps --> PostgreSQL
    Cron_Jobs --> fetch_data
    Cron_Jobs --> transform_data
    Cron_Jobs --> push_fhir_data
    
    style fetch_data fill:#f9f,stroke:#333,stroke-width:2px
    style transform_data fill:#f9f,stroke:#333,stroke-width:2px
    style push_fhir_data fill:#f9f,stroke:#333,stroke-width:2px
    style device_management fill:#f9f,stroke:#333,stroke-width:2px
    style metrics fill:#f9f,stroke:#333,stroke-width:2px
```

## Key Technical Decisions
- **Django and DRF:** Chosen for rapid development, robust ORM, admin interface, and REST API framework.
- **PostgreSQL:**  Reliable and feature-rich relational database suitable for Django.
- **Redis:**  Efficient task queue and caching mechanism for asynchronous tasks and improved performance.
- **Hypercorn:** ASGI server for handling asynchronous requests and WebSocket connections if needed in the future.
- **Kubernetes:** Container orchestration platform for scalable and resilient deployment.
- **Prometheus:** Industry-standard metrics monitoring and alerting system.
- **FHIR R5:** Latest FHIR standard for interoperability with modern EHR systems.
- **OAuth2:** Preferred authentication standard for both third-party providers and FHIR server.

## Design Patterns
- **Micro-service Architecture:**  Breaking down functionality into independent, scalable services (Django apps).
- **Asynchronous Task Processing:**  Using Redis and Celery (or similar) for offloading data fetching, transformation, and pushing tasks.
- **RESTful API Design:**  Using DRF to create well-defined and documented APIs for configuration and management.
- **Data Mapping and Transformation:**  Implementing flexible and configurable data mapping logic, potentially using a mapping engine or DSL.
- **Observability:**  Integrating Prometheus for metrics, logging, and tracing for monitoring and debugging.

## Component Relationships
- **`device_management` App:** Manages connections to third-party providers, stores configuration, and exposes APIs for device and connection management.
- **`fetch_data` App:**  Retrieves data from third-party APIs, enqueues tasks for data transformation.
- **`transform_data` App:**  Consumes tasks from Redis, transforms data to FHIR R5, enqueues tasks for pushing to FHIR server.
- **`push_fhir_data` App:** Consumes tasks from Redis, pushes FHIR R5 resources to the EHR system, handles duplicate checking and error scenarios.
- **`metrics` App:**  Collects and exposes application metrics in Prometheus format.
- **REST API:**  Provides entry points for UI and external clients to interact with the micro-service, manage configurations, trigger sync operations, and monitor status.
- **Cron Jobs:** Scheduled tasks to trigger nightly data synchronization.
