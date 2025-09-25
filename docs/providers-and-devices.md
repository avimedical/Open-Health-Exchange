# Supported Providers and Devices

## Overview

Open Health Exchange currently supports two major health data providers: **Withings** and **Fitbit**. Each provider offers different device types and health data capabilities.

## Provider Support Matrix

| Provider | OAuth2 | Webhooks | Device Sync | Health Data | Status |
|----------|--------|----------|-------------|-------------|--------|
| Withings | ✅ | ✅ | ✅ | ✅ | Production Ready |
| Fitbit   | ✅ | ✅ | ✅ | ✅ | Production Ready |

## Withings Integration

### Supported Devices

```mermaid
graph LR
    subgraph "Withings Ecosystem"
        subgraph "Body Composition"
            BS[Body+ Scale]
            BC[Body Cardio]
            BM[Body Comp]
        end

        subgraph "Activity Tracking"
            SA[ScanWatch]
            S2[ScanWatch 2]
            SP[Steel HR Sport]
        end

        subgraph "Health Monitoring"
            BP[BPM Connect]
            TH[Thermo]
            SM[Sleep Mat]
        end
    end

    BS --> WA[Withings API]
    BC --> WA
    BM --> WA
    SA --> WA
    S2 --> WA
    SP --> WA
    BP --> WA
    TH --> WA
    SM --> WA
```

### Device Categories and Data Types

| Device Type | SNOMED CT Code | Data Types Supported | FHIR Resource |
|-------------|----------------|---------------------|---------------|
| **Body Scale** | 19892000 (Scale) | Weight, BMI, Fat %, Muscle Mass | Observation |
| **Activity Tracker** | 466093008 (Activity tracker) | Steps, Heart Rate, Sleep | Observation |
| **Smartwatch** | 706767009 (Wearable device) | Heart Rate, RR Intervals, ECG | Observation |
| **Blood Pressure Monitor** | 43770009 (Sphygmomanometer) | Systolic/Diastolic BP, Pulse | Observation |
| **Thermometer** | 86184003 (Thermometer) | Body Temperature | Observation |

### Withings API Integration

```mermaid
sequenceDiagram
    participant U as User
    participant A as Open Health Exchange
    participant W as Withings API
    participant WD as Withings Device

    U->>A: Initiate Withings connection
    A->>W: OAuth2 authorization request
    W->>U: User consent screen
    U->>W: Grant permission
    W->>A: Authorization code
    A->>W: Exchange for access token
    W->>A: Access token + refresh token

    Note over A,W: Setup webhook subscription
    A->>W: Subscribe to notifications
    W->>A: Webhook subscription confirmed

    Note over WD,A: Real-time data flow
    WD->>W: Sync health data
    W->>A: Webhook notification
    A->>W: Fetch detailed data
    W->>A: Health data response
    A->>A: Transform to FHIR
```

### Withings Data Mapping

| Withings Data Type | Application ID | LOINC Code | FHIR Category |
|-------------------|----------------|------------|---------------|
| Heart Rate | 4, 44 | 8867-4 | vital-signs |
| Steps | 4 | 55423-8 | activity |
| Weight | 1 | 29463-7 | vital-signs |
| Blood Pressure | 46 | 85354-9 (Systolic), 8462-4 (Diastolic) | vital-signs |
| Body Temperature | 12 | 8310-5 | vital-signs |
| RR Intervals | 44 | 80404-7 | vital-signs |
| ECG | 50 | 131328-5 | procedure |

## Fitbit Integration

### Supported Devices

```mermaid
graph LR
    subgraph "Fitbit Ecosystem"
        subgraph "Premium Trackers"
            FC[Charge 6]
            FS[Sense 2]
            FV[Versa 4]
        end

        subgraph "Fitness Trackers"
            FI[Inspire 3]
            FL[Luxe]
        end

        subgraph "Smart Scales"
            FA[Aria 2]
            AA[Aria Air]
        end
    end

    FC --> FA_API[Fitbit API]
    FS --> FA_API
    FV --> FA_API
    FI --> FA_API
    FL --> FA_API
    FA --> FA_API
    AA --> FA_API
```

### Device Categories and Data Types

| Device Type | SNOMED CT Code | Data Types Supported | FHIR Resource |
|-------------|----------------|---------------------|---------------|
| **Fitness Tracker** | 466093008 (Activity tracker) | Steps, Heart Rate, Sleep, Activity | Observation |
| **Smartwatch** | 706767009 (Wearable device) | Heart Rate, ECG, SpO2, Stress | Observation |
| **Smart Scale** | 19892000 (Scale) | Weight, BMI, Body Fat % | Observation |

### Fitbit API Integration

```mermaid
sequenceDiagram
    participant U as User
    participant A as Open Health Exchange
    participant F as Fitbit API
    participant FD as Fitbit Device

    U->>A: Initiate Fitbit connection
    A->>F: OAuth2 authorization request
    F->>U: User consent screen
    U->>F: Grant permission
    F->>A: Authorization code
    A->>F: Exchange for access token
    F->>A: Access token + refresh token

    Note over A,F: Setup webhook subscription
    A->>F: Create API subscription
    F->>A: Subscription confirmed

    Note over FD,A: Real-time data flow
    FD->>F: Sync health data
    F->>A: Webhook notification
    A->>F: Fetch detailed data
    F->>A: Health data response
    A->>A: Transform to FHIR
```

### Fitbit Data Mapping

| Fitbit Collection Type | LOINC Code | FHIR Category | Description |
|------------------------|------------|---------------|-------------|
| activities | 55423-8 | activity | Steps, distance, calories |
| heart | 8867-4 | vital-signs | Heart rate zones, resting HR |
| sleep | 93832-4 | activity | Sleep stages, duration |
| body | 29463-7 | vital-signs | Weight, BMI, body fat |
| spo2 | 2708-6 | vital-signs | Blood oxygen saturation |

## Authentication and Authorization

### OAuth2 Flow Comparison

```mermaid
graph TB
    subgraph "Withings OAuth2"
        WC[Client Registration]
        WA[Authorization Request]
        WU[User Consent]
        WT[Token Exchange]
        WR[Refresh Token]
    end

    subgraph "Fitbit OAuth2"
        FC[Client Registration]
        FA[Authorization Request]
        FU[User Consent]
        FT[Token Exchange]
        FR[Refresh Token]
    end

    WC --> WA --> WU --> WT --> WR
    FC --> FA --> FU --> FT --> FR

    WT -.->|Access Token| WAPI[Withings API Calls]
    FT -.->|Access Token| FAPI[Fitbit API Calls]
```

### Required Scopes

#### Withings Scopes
- `user.info`: Basic user information
- `user.metrics`: Health measurements
- `user.activity`: Activity and exercise data

#### Fitbit Scopes
- `activity`: Steps, distance, calories, active minutes
- `heartrate`: Heart rate data
- `location`: GPS data (if needed)
- `nutrition`: Food and water logging
- `profile`: Basic profile information
- `settings`: User preferences
- `sleep`: Sleep logs
- `social`: Friends and leaderboards
- `weight`: Body weight and BMI

## Device Discovery and Management

### Device Registration Flow

```mermaid
flowchart TD
    A[User Connects Provider] --> B[OAuth2 Authentication]
    B --> C[Fetch User Devices]
    C --> D[Create FHIR Device Resources]
    D --> E[Create DeviceAssociation]
    E --> F[Setup Webhook Subscriptions]
    F --> G[Background Sync Enabled]

    C --> H{Device Already Exists?}
    H -->|Yes| I[Update Device Info]
    H -->|No| J[Create New Device]
    I --> E
    J --> D
```

### Device Properties Tracked

| Property | Withings | Fitbit | FHIR Mapping |
|----------|----------|--------|--------------|
| Device ID | ✅ | ✅ | identifier.value |
| Model Name | ✅ | ✅ | name |
| Battery Level | ✅ | ✅ | property.battery-level |
| Firmware Version | ✅ | ✅ | version.value |
| Last Sync Time | ✅ | ✅ | property.lastSyncTime |
| MAC Address | ❌ | ✅ | identifier.value (secondary) |
| Serial Number | ❌ | ❌ | identifier.value (if available) |

## Data Synchronization Patterns

### Real-Time Webhook Triggers

```mermaid
graph LR
    subgraph "Trigger Events"
        WS[Weight Measurement]
        HR[Heart Rate Reading]
        ST[Step Count Update]
        SL[Sleep Data]
        BP[Blood Pressure]
    end

    subgraph "Webhook Processing"
        WH[Webhook Received]
        VL[Validate Signature]
        PR[Process Payload]
        QT[Queue Task]
    end

    subgraph "Background Sync"
        FD[Fetch Detailed Data]
        TR[Transform to FHIR]
        PU[Publish to EHR]
    end

    WS --> WH
    HR --> WH
    ST --> WH
    SL --> WH
    BP --> WH

    WH --> VL --> PR --> QT
    QT --> FD --> TR --> PU
```

### Data Freshness and Timing

| Provider | Webhook Latency | Data Freshness | Retry Policy |
|----------|----------------|----------------|--------------|
| Withings | < 5 minutes | Near real-time | 3 retries with exponential backoff |
| Fitbit | < 15 minutes | Near real-time | 3 retries with exponential backoff |

## Error Handling and Limitations

### Common Integration Challenges

```mermaid
mindmap
  root((Integration Challenges))
    API Rate Limits
      Withings: 300 req/5min
      Fitbit: 150 req/hour
    Token Management
      Access Token Expiry
      Refresh Token Rotation
      User Revocation
    Data Quality
      Missing Measurements
      Device Synchronization
      Duplicate Data
    Webhook Reliability
      Network Failures
      Signature Validation
      Payload Processing
```

### Error Recovery Strategies

| Error Type | Withings | Fitbit | Recovery Strategy |
|------------|----------|--------|-------------------|
| Rate Limit | 429 HTTP | 429 HTTP | Exponential backoff, queue tasks |
| Auth Failure | 401 HTTP | 401 HTTP | Refresh token, re-authenticate user |
| Network Error | Timeout | Timeout | Retry with circuit breaker |
| Invalid Data | Parse Error | Parse Error | Log error, skip record |

## Future Provider Support

### Planned Integrations

```mermaid
timeline
    title Provider Roadmap

    Phase 1 : Withings
            : Fitbit

    Phase 2 : Apple Health
            : Google Fit

    Phase 3 : Samsung Health
            : Garmin Connect

    Phase 4 : Oura Ring
            : Polar Flow
```

### Extension Framework

The system is designed to easily support new providers through:

1. **Provider Registration**: Add new provider configuration
2. **OAuth2 Backend**: Implement provider-specific authentication
3. **API Client**: Create provider API integration
4. **Data Mapping**: Define FHIR transformation rules
5. **Webhook Handler**: Process provider notifications

### Adding New Providers

```python
# Example provider configuration
PROVIDER_CONFIGS = {
    Provider.NEW_PROVIDER: ProviderConfig(
        name=Provider.NEW_PROVIDER,
        client_id_setting="SOCIAL_AUTH_NEWPROVIDER_KEY",
        client_secret_setting="SOCIAL_AUTH_NEWPROVIDER_SECRET",
        api_base_url="https://api.newprovider.com",
        device_endpoint="/v1/devices",
        device_types_map={
            "tracker": DeviceType.ACTIVITY_TRACKER,
            "scale": DeviceType.SCALE,
        }
    )
}
```

This extensible architecture ensures that adding new health data providers follows a consistent pattern and maintains compatibility with the existing FHIR integration.