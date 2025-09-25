# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Open Health Exchange is a Django-based microservice that synchronizes health data from third-party providers (Withings, Fitbit) to FHIR R5-based Electronic Health Record (EHR) systems. The service acts as middleware without storing health data, only configuration and mapping details.

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
black .                          # Format code (line length: 120)
flake8                          # Lint code
```

### Background Tasks
```bash
python manage.py run_huey        # Start Huey task queue consumer
```

### Testing Commands
```bash
python test_phase3_simple.py     # Test monitoring and observability features
python test_phase2_compatibility.py  # Test Phase 2 API compatibility
python test_health_sync_phase1.py    # Test Phase 1 health sync
```

## Architecture (Phase 3 Complete - Production Ready)

### Core Django Apps
- **base/**: Core models (EHRUser, ProviderLink), OAuth2 backends, REST API endpoints with DRF ViewSets
- **ingestors/**: Data ingestion with circuit breakers, error handling, and retry logic
- **transformers/**: Data transformation and mapping to FHIR R5 resources
- **publishers/**: Publishing transformed data to FHIR servers
- **webhooks/**: Production webhook endpoints with signature validation
- **metrics/**: Prometheus metrics, health checks, structured logging, and observability

### Key Technologies
- **Framework**: Django 5.2 with Django REST Framework
- **API Design**: ViewSet-based REST APIs with proper serializers
- **Database**: PostgreSQL (configured via DATABASE_URL)
- **Task Queue**: Huey with Redis backend
- **Server**: Daphne (ASGI)
- **FHIR**: fhirpy library for FHIR R5 interaction
- **OAuth2**: python-social-auth with custom backends
- **Authentication**: mozilla-django-oidc for OIDC integration

### Configuration
- Environment variables loaded via python-dotenv from `.env` file
- OAuth2 credentials configured via environment variables (WITHINGS_CLIENT_ID, FITBIT_CLIENT_ID, etc.)
- Custom user model: `base.EHRUser`
- Redis used for both Huey task queue and Django caching
- Huey configured with PriorityRedisExpireHuey for Redis 8 compatibility with connection pooling

### Data Flow Architecture
1. **Provider Connection**: Users connect to health data providers via OAuth2 flow (`/api/base/link/{provider}/`)
2. **Webhook Registration**: Providers send real-time notifications to webhook endpoints (`/webhooks/{provider}/`)
3. **Background Sync**: Webhook notifications trigger Huey tasks for data ingestion
4. **Data Pipeline**: Ingestors → Transformers → Publishers (all background tasks)
5. **FHIR Output**: Health data and device information published as FHIR R5 resources

### REST API Endpoints (Django REST Framework)

#### Base API (`/api/base/`)
- `GET /api/base/providers/` - List available health data providers
- `GET /api/base/providers/capabilities/` - Get supported data types and features
- `GET /api/base/sync/status/` - Check synchronization status for users
- `GET /api/base/sync/providers/` - List connected providers for a user
- `POST /api/base/sync/trigger_device_sync/` - Trigger device sync (admin/testing)
- `GET /api/base/link/{provider}/` - Initiate OAuth2 provider linking
- `GET /api/base/link/{provider}/status/` - Check provider connection status

#### Webhook Endpoints (`/webhooks/`)
- `POST/GET /webhooks/withings/` - Withings webhook notifications
- `POST/GET /webhooks/fitbit/` - Fitbit webhook notifications
- `GET /webhooks/health/` - Health check endpoint
- `GET /webhooks/metrics/` - Webhook metrics and statistics

#### Monitoring & Health Check Endpoints (`/api/metrics/`)
- `GET /api/metrics/health/` - Comprehensive health check (database, Redis, Huey)
- `GET /api/metrics/ready/` - Kubernetes readiness probe
- `GET /api/metrics/live/` - Kubernetes liveness probe
- `GET /api/metrics/metrics/` - Prometheus metrics in text format

### Authentication Architecture
- Custom OAuth2 backends for Withings and Fitbit in `base/backends.py`
- Social auth pipeline in `base/pipeline.py` links provider accounts to existing users
- OIDC integration for EHR system authentication
- No new user creation - only account linking for existing EHR users
- DRF built-in authentication, permissions, and throttling

### Security & Error Handling
- Django REST Framework built-in security features
- Input validation via DRF serializers
- HMAC signature validation for webhooks
- Rate limiting via DRF throttling
- Comprehensive error handling with structured responses
- Audit logging for sensitive operations

### Production Monitoring & Observability (Phase 3)

#### Prometheus Metrics Collection
- **Application Metrics**: Sync operations, data points processed, API requests
- **System Metrics**: Database connections, Redis connections, Huey queue size
- **Provider Metrics**: API errors, rate limits, webhook processing times
- **FHIR Metrics**: Operation counts, response times by resource type

#### Circuit Breaker Patterns
- **Provider Protection**: Circuit breakers for Withings and Fitbit APIs
- **FHIR Protection**: Circuit breaker for FHIR server calls
- **Configurable Thresholds**: Failure thresholds, timeout periods, recovery times
- **Automatic Recovery**: Half-open state testing for service recovery

#### Error Handling & Classification
- **Error Types**: API, Auth, Rate Limit, Network, Validation errors
- **Retry Logic**: Configurable retry handlers with exponential backoff
- **Metrics Integration**: All errors recorded in Prometheus metrics
- **Structured Logging**: Error context included in JSON logs

#### Health Checks
- **Database Health**: Connection pool and query execution
- **Redis Health**: Cache availability and response times
- **Huey Health**: Task queue availability and size
- **Overall Status**: Aggregated health with proper HTTP status codes

#### Structured Logging
- **JSON Format**: Production logs in structured JSON format
- **Context Fields**: User ID, provider, operation, duration
- **Log Levels**: Configurable per module (INFO, WARNING, ERROR)
- **Middleware Integration**: Automatic request/response logging

### Background Task System
- **Trigger**: Webhooks from providers or scheduled cron jobs
- **Execution**: Huey tasks for data ingestion, transformation, and publishing
- **No Manual APIs**: Sync happens automatically, not via manual API calls
- **Monitoring**: Status available via API endpoints

### Implementation Status (Phase 3 Complete - Production Ready)

#### Phase 1: Core Infrastructure ✅
- ✅ Health data models and constants
- ✅ FHIR R5 transformers for observations
- ✅ Health data publishers
- ✅ Sync orchestration service
- ✅ Huey background tasks

#### Phase 2: Real Integration ✅
- ✅ OAuth2 flows for Withings/Fitbit with proper backends
- ✅ Production webhook endpoints with signature validation
- ✅ FHIR Device management with Device and DeviceAssociation resources
- ✅ Real API clients for Withings and Fitbit with token refresh
- ✅ DRF-based REST APIs with ViewSets and serializers
- ✅ Health data sync infrastructure with proper task queuing

#### Phase 3: Production Monitoring ✅
- ✅ **Prometheus metrics** collection and exposure
- ✅ **Health check endpoints** for Kubernetes deployment
- ✅ **Circuit breakers** for external API resilience
- ✅ **Structured JSON logging** for production observability
- ✅ **Error handling** with classification and retry logic
- ✅ **Metrics middleware** for automatic request tracking

### FHIR R5 Integration
- **Device Resources**: SNOMED CT coded device types
- **DeviceAssociation Resources**: Patient-device relationships
- **Observation Resources**: Health data with LOINC coding
- **Patient References**: Links to EHR system patients
- **Identifier Systems**: Provider-specific identification

### Data Types Supported
- Heart rate (LOINC: 8867-4)
- Steps (LOINC: 55423-8)
- RR intervals (heart rate variability)
- ECG data
- Blood pressure
- Weight measurements
- Device information and battery status

### Important Notes
- **No health data storage** - service acts as a pass-through transformer
- **Webhook-driven architecture** - real-time sync via provider notifications
- **Background processing only** - no manual sync APIs
- **FHIR R5 compliant** - modern healthcare interoperability
- **Production ready** - comprehensive security, error handling, monitoring
- **Horizontally scalable** - stateless design with Redis backing