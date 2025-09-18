# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Health Exchange is a Django-based microservice that synchronizes health data from third-party providers (Withings, Fitbit, Omron, Beurer) to FHIR R5-based Electronic Health Record (EHR) systems. The service acts as middleware without storing health data, only configuration and mapping details.

### Purpose
Bridges the gap between personal health data from wearables and EHR systems by:
- Breaking down data silos across different health apps/devices
- Automating manual data entry processes
- Providing healthcare providers access to patient-generated health data
- Enabling FHIR R5 compliant integration with modern EHR systems

## Development Commands

### Environment Setup
```bash
poetry install                    # Install dependencies
poetry shell                     # Activate virtual environment
```

### Database Operations
```bash
python manage.py migrate         # Run database migrations
python manage.py makemigrations  # Create new migrations
```

### Development Server
```bash
python manage.py runserver       # Start Django development server
```

### Code Quality
```bash
black .                          # Format code (line length: 140)
flake8                          # Lint code
```

### Background Tasks
```bash
python manage.py run_huey        # Start Huey task queue consumer
```

## Architecture

### Core Django Apps
- **base/**: Core models (EHRUser, ProviderLink), OAuth2 backends for Withings/Fitbit, authentication pipeline
- **ingestors/**: Data ingestion from third-party health providers (background tasks)
- **transformers/**: Data transformation and mapping to FHIR R5 resources
- **publishers/**: Publishing transformed data to FHIR servers
- **metrics/**: Prometheus metrics exposure for monitoring

### Key Technologies
- **Framework**: Django 5.2b1 with Django REST Framework
- **Database**: PostgreSQL (configured via DATABASE_URL)
- **Task Queue**: Huey with Redis backend
- **Server**: Hypercorn (ASGI)
- **FHIR**: fhirpy library for FHIR R5 interaction
- **OAuth2**: python-social-auth with custom backends
- **Authentication**: mozilla-django-oidc for OIDC integration

### Configuration
- Environment variables loaded via python-dotenv from `.env` file
- OAuth2 credentials configured via environment variables (WITHINGS_CLIENT_ID, FITBIT_CLIENT_ID, etc.)
- Custom user model: `base.EHRUser`
- Redis used for both Huey task queue and Django caching

### Data Flow
1. **Configuration**: Users configure connections to third-party providers and EHR systems via REST API
2. **Ingestors** fetch data from provider APIs using OAuth2 tokens (background tasks via Huey)
3. **Transformers** convert provider-specific data to FHIR R5 format with configurable mappings
4. **Publishers** send FHIR resources to EHR systems with duplicate checking and error handling
5. **Metrics** track synchronization success/failure rates and expose to Prometheus

### Authentication Architecture
- Custom OAuth2 backends for Withings and Fitbit in `base/backends.py`
- Social auth pipeline in `base/pipeline.py` links provider accounts to existing users
- OIDC integration for EHR system authentication
- No new user creation - only account linking for existing EHR users
- JWT/OAuth2 support for FHIR server authentication

### Current Implementation Status
- **Complete**: OAuth2 flows for Withings/Fitbit, user authentication, basic app structure
- **In Progress**: FHIR Device creation and Device Management API endpoints
- **Planned**: Data ingestion tasks, FHIR transformation logic, metrics collection, Kubernetes deployment

### Important Notes
- No health data storage - service acts as a pass-through transformer
- Horizontal scaling via Kubernetes deployment with independent worker scaling
- Background sync jobs for nightly data synchronization (cron-based)
- Rate limiting and retry mechanisms for third-party API calls
- Uses Huey task queue with Redis backend for asynchronous processing
- API versioning via Accept header (AcceptHeaderVersioning)