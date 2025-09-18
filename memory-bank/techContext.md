# Technical Context: Health Data Sync Micro-service

## Technologies Used
- **Programming Language:** Python 3.x
- **Framework:** Django 4.x or later
- **REST API Framework:** Django REST Framework
- **Database:** PostgreSQL
- **Task Queue:** Huey, Redis, Huey PriorityQueue
- **Application Server:** Hypercorn
- **Containerization:** Docker
- **Orchestration:** Kubernetes
- **Metrics and Monitoring:** Prometheus, Grafana (optional for dashboards)
- **FHIR Library:**  `fhirpy` or `fhirclient` Python library for FHIR R5 interaction
- **Authentication Libraries:** `django-oauth-toolkit` or similar for OAuth2, `PyJWT` for JWT
- **Code Formatting:** Black
- **Code Linting:** Flake8

## Development Setup
- **Environment Management:** Poetry for dependency management and virtual environments.
- **Code Style & Formatting:** Black, Flake8
- **Testing:** Pytest, Django test framework
- **Linting:** Flake8
- **IDE:** VSCode (recommended) or any Python IDE
- **Local Deployment:** Docker Compose for local development and testing.

## Technical Constraints
- **Third-Party API Limits:**  Respect rate limits and usage quotas of third-party provider APIs. Implement proper error handling and retry mechanisms.
- **Data Mapping Complexity:**  Data models of third-party providers may vary significantly. Design a flexible and configurable mapping approach.
- **FHIR R5 Compliance:** Ensure generated FHIR resources are valid and conform to FHIR R5 specifications.
- **Security:**  Securely store and manage API credentials, OAuth2 tokens, and FHIR server authentication details. Implement secure communication channels (HTTPS).
- **Scalability and Performance:** Design for horizontal scalability and optimize performance for data synchronization tasks.
- **Data Volume:**  Handle potentially large volumes of health data from multiple providers and users.

## Dependencies
- **Python Packages (Poetry - Core):**
    - Django
    - djangorestframework
    - hypercorn
    - psycopg2-binary (PostgreSQL driver)
    - redis
    - huey
    - prometheus-client
    - fhirpy or fhirclient
    - requests-oauthlib or similar OAuth2 library
    - PyJWT (if JWT is used for FHIR auth)
    - django-environ (for environment variable management)
    - drf-spectacular (for API documentation)
    - any other necessary packages for specific provider APIs (e.g., Withings, Fitbit SDKs if available)
- **Python Packages (Poetry - Development):**
    - black
    - flake8

- **System Dependencies:**
    - PostgreSQL server
    - Redis server
    - Docker and Docker Compose (for development)
    - Kubernetes cluster (for deployment)
    - Prometheus server (for monitoring)
