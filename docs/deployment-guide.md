# Deployment Guide

## Overview

This guide covers deploying Open Health Exchange to production environments using Kubernetes, with comprehensive monitoring, security, and scalability configurations.

## Infrastructure Architecture

> NOTE: The diagram is technology-neutral about clustering/HA — use managed or self-hosted Valkey/Redis and PostgreSQL (single instance, HA, or cluster) according to your SLOs.

```mermaid
graph TB
    subgraph "External"
        U[Users/EHR Systems]
        P[Health Providers<br/>Withings/Fitbit]
    end

    subgraph "Load Balancer"
        LB[nginx Ingress Controller]
        SSL[TLS Termination]
    end

    subgraph "Kubernetes Cluster"
        subgraph "Application Pods"
            W1[Web Pod 1<br/>Django]
            W2[Web Pod 2<br/>Django]
            WN[Web Pod N<br/>Django]
        end

        subgraph "Worker Pods"
            H1[Huey Worker 1]
            H2[Huey Worker 2]
            HN[Huey Worker N]
        end

    subgraph "Data Layer"
      R[Valkey / Redis Service]
      P_DB[(PostgreSQL Service)]
        end

    subgraph "Monitoring"
      PR[Prometheus Metrics]
      GR[Grafana (Optional)]
      AL[Alerting System (Optional)]
        end
    end

    subgraph "External Services"
        FHIR[FHIR Server]
        LOGS[Log Aggregation<br/>ELK/Fluentd]
    end

    U --> LB
    P --> LB
    LB --> SSL
    SSL --> W1
    SSL --> W2
    SSL --> WN

    W1 --> R
    W2 --> R
    WN --> R
    H1 --> R
    H2 --> R
    HN --> R

    W1 --> P_DB
    W2 --> P_DB
    WN --> P_DB
    H1 --> P_DB
    H2 --> P_DB
    HN --> P_DB

    H1 --> FHIR
    H2 --> FHIR
    HN --> FHIR

    PR --> W1
    PR --> W2
    PR --> H1
    PR --> H2
    GR --> PR
    AL --> PR

    W1 --> LOGS
    H1 --> LOGS
```

## Kubernetes Configuration

### Namespace and ConfigMap

```yaml
# namespace.yaml
apiVersion: v1
kind: Namespace
metadata:
  name: open-health-exchange
  labels:
    name: open-health-exchange

---
# configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: ohe-config
  namespace: open-health-exchange
data:
  DEBUG: "False"
  ALLOWED_HOSTS: "api.open-health-exchange.org,*.open-health-exchange.org"
  DATABASE_URL: "postgresql://ohe_user:$(DB_PASSWORD)@postgres-service:5432/open_health_exchange"
  # Valkey/Redis connection(s)
  REDIS_URL: "redis://valkey:6379/0"
  # Optional separate logical DB if isolating cache from queue
  REDIS_CACHE_URL: "redis://valkey:6379/1"
  # Huey shares REDIS_URL (no separate broker service)

  # FHIR Configuration
  FHIR_BASE_URL: "https://fhir.example.org/R5"
  FHIR_AUTH_METHOD: "oauth2"

  # Security Settings
  SECURE_SSL_REDIRECT: "True"
  SECURE_HSTS_SECONDS: "31536000"
  SECURE_HSTS_INCLUDE_SUBDOMAINS: "True"
  SECURE_HSTS_PRELOAD: "True"

  # Rate Limiting
  # API rate limiting (DRF throttling). Advanced provider backoff *Planned*.
  RATELIMIT_ENABLE: "True"
  RATELIMIT_USE_CACHE: "default"

  # Monitoring
  PROMETHEUS_ENABLED: "True"
  SENTRY_ENABLED: "False"  # Set to True when Sentry integrated (*Planned*)
```

### Secrets Management

```yaml
# secrets.yaml
apiVersion: v1
kind: Secret
metadata:
  name: ohe-secrets
  namespace: open-health-exchange
type: Opaque
stringData:
  SECRET_KEY: "your-super-secret-django-key-here"
  DB_PASSWORD: "secure-database-password"

  # Provider OAuth Credentials
  SOCIAL_AUTH_WITHINGS_KEY: "withings-client-id"
  SOCIAL_AUTH_WITHINGS_SECRET: "withings-client-secret"
  SOCIAL_AUTH_FITBIT_KEY: "fitbit-client-id"
  SOCIAL_AUTH_FITBIT_SECRET: "fitbit-client-secret"

  # Webhook Secrets
  WITHINGS_WEBHOOK_SECRET: "withings-webhook-secret"

  # FHIR Authentication
  FHIR_CLIENT_ID: "fhir-client-id"
  FHIR_CLIENT_SECRET: "fhir-client-secret"

  # Monitoring
  SENTRY_DSN: "https://your-sentry-dsn@sentry.io/project"
```

### Application Deployment

```yaml
# deployment-web.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ohe-web
  namespace: open-health-exchange
  labels:
    app: ohe-web
    tier: web
spec:
  replicas: 3
  selector:
    matchLabels:
      app: ohe-web
      tier: web
  template:
    metadata:
      labels:
        app: ohe-web
        tier: web
    spec:
      containers:
      - name: web
        image: open-health-exchange/web:latest
        ports:
        - containerPort: 8000
          name: http
        envFrom:
        - configMapRef:
            name: ohe-config
        - secretRef:
            name: ohe-secrets
        env:
        - name: POD_NAME
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
        - name: POD_NAMESPACE
          valueFrom:
            fieldRef:
              fieldPath: metadata.namespace
        livenessProbe:
          httpGet:
            path: /webhooks/health/
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
          timeoutSeconds: 5
          failureThreshold: 3
        readinessProbe:
          httpGet:
            path: /webhooks/health/
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
          timeoutSeconds: 3
          failureThreshold: 3
        resources:
          requests:
            memory: "256Mi"
            cpu: "100m"
          limits:
            memory: "512Mi"
            cpu: "500m"
        securityContext:
          allowPrivilegeEscalation: false
          runAsNonRoot: true
          runAsUser: 1000
          capabilities:
            drop:
            - ALL

---
# deployment-worker.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ohe-worker
  namespace: open-health-exchange
  labels:
    app: ohe-worker
    tier: worker
spec:
  replicas: 2
  selector:
    matchLabels:
      app: ohe-worker
      tier: worker
  template:
    metadata:
      labels:
        app: ohe-worker
        tier: worker
    spec:
      containers:
      - name: worker
        image: open-health-exchange/worker:latest
        command: ["python", "manage.py", "run_huey"]
        envFrom:
        - configMapRef:
            name: ohe-config
        - secretRef:
            name: ohe-secrets
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "1000m"
        securityContext:
          allowPrivilegeEscalation: false
          runAsNonRoot: true
          runAsUser: 1000
          capabilities:
            drop:
            - ALL
```

### Services and Ingress

```yaml
# service.yaml
apiVersion: v1
kind: Service
metadata:
  name: ohe-web-service
  namespace: open-health-exchange
  labels:
    app: ohe-web
spec:
  selector:
    app: ohe-web
    tier: web
  ports:
  - port: 80
    targetPort: 8000
    protocol: TCP
    name: http
  type: ClusterIP

---
# ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: ohe-ingress
  namespace: open-health-exchange
  annotations:
    kubernetes.io/ingress.class: "nginx"
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
    nginx.ingress.kubernetes.io/rate-limit: "100"
    nginx.ingress.kubernetes.io/rate-limit-window: "1m"
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  tls:
  - hosts:
    - api.open-health-exchange.org
    secretName: ohe-tls-secret
  rules:
  - host: api.open-health-exchange.org
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: ohe-web-service
            port:
              number: 80
```

### Horizontal Pod Autoscaler

```yaml
# hpa.yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ohe-web-hpa
  namespace: open-health-exchange
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ohe-web
  minReplicas: 3
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80

---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: ohe-worker-hpa
  namespace: open-health-exchange
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: ohe-worker
  minReplicas: 2
  maxReplicas: 8
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 80
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 85
```

## Database Configuration

### PostgreSQL with High Availability

```yaml
# postgres.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: postgres-primary
  namespace: open-health-exchange
spec:
  serviceName: postgres-primary
  replicas: 1
  selector:
    matchLabels:
      app: postgres
      role: primary
  template:
    metadata:
      labels:
        app: postgres
        role: primary
    spec:
      containers:
      - name: postgres
        image: postgres:15-alpine
        env:
        - name: POSTGRES_DB
          value: "open_health_exchange"
        - name: POSTGRES_USER
          value: "ohe_user"
        - name: POSTGRES_PASSWORD
          valueFrom:
            secretKeyRef:
              name: ohe-secrets
              key: DB_PASSWORD
        - name: POSTGRES_REPLICATION_USER
          value: "replicator"
        - name: POSTGRES_REPLICATION_PASSWORD
          value: "replication_password"
        ports:
        - containerPort: 5432
        volumeMounts:
        - name: postgres-storage
          mountPath: /var/lib/postgresql/data
        - name: postgres-config
          mountPath: /etc/postgresql/postgresql.conf
          subPath: postgresql.conf
        resources:
          requests:
            memory: "1Gi"
            cpu: "500m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
      volumes:
      - name: postgres-config
        configMap:
          name: postgres-config
  volumeClaimTemplates:
  - metadata:
      name: postgres-storage
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 50Gi
      storageClassName: fast-ssd
```

### Redis Cluster Configuration

```yaml
# redis-cluster.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: redis-cluster
  namespace: open-health-exchange
spec:
  serviceName: redis-cluster
  replicas: 3
  selector:
    matchLabels:
      app: redis-cluster
  template:
    metadata:
      labels:
        app: redis-cluster
    spec:
      containers:
      - name: redis
        image: redis:7-alpine
        command:
        - redis-server
        - /etc/redis/redis.conf
        ports:
        - containerPort: 6379
          name: client
        - containerPort: 16379
          name: gossip
        volumeMounts:
        - name: redis-config
          mountPath: /etc/redis
        - name: redis-data
          mountPath: /data
        resources:
          requests:
            memory: "512Mi"
            cpu: "200m"
          limits:
            memory: "1Gi"
            cpu: "500m"
      volumes:
      - name: redis-config
        configMap:
          name: redis-config
  volumeClaimTemplates:
  - metadata:
      name: redis-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: 10Gi
```

## Monitoring and Observability

### Prometheus Configuration

```yaml
# prometheus.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: prometheus
  namespace: open-health-exchange
spec:
  replicas: 1
  selector:
    matchLabels:
      app: prometheus
  template:
    metadata:
      labels:
        app: prometheus
    spec:
      containers:
      - name: prometheus
        image: prom/prometheus:latest
        ports:
        - containerPort: 9090
        volumeMounts:
        - name: prometheus-config
          mountPath: /etc/prometheus
        - name: prometheus-storage
          mountPath: /prometheus
        command:
        - /bin/prometheus
        - --config.file=/etc/prometheus/prometheus.yml
        - --storage.tsdb.path=/prometheus
        - --web.console.libraries=/usr/share/prometheus/console_libraries
        - --web.console.templates=/usr/share/prometheus/consoles
        - --web.enable-lifecycle
        - --storage.tsdb.retention.time=30d
      volumes:
      - name: prometheus-config
        configMap:
          name: prometheus-config
      - name: prometheus-storage
        persistentVolumeClaim:
          claimName: prometheus-storage

---
# prometheus-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-config
  namespace: open-health-exchange
data:
  prometheus.yml: |
    global:
      scrape_interval: 15s
      evaluation_interval: 15s

    rule_files:
      - "alert_rules.yml"

    alerting:
      alertmanagers:
        - static_configs:
            - targets:
              - alertmanager:9093

    scrape_configs:
    - job_name: 'ohe-web'
      kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
          - open-health-exchange
      relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: ohe-web
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_scrape]
        action: keep
        regex: true
      - source_labels: [__meta_kubernetes_pod_annotation_prometheus_io_port]
        action: replace
        target_label: __address__
        regex: ([^:]+)(?::\d+)?;(\d+)
        replacement: $1:$2

    - job_name: 'ohe-worker'
      kubernetes_sd_configs:
      - role: pod
        namespaces:
          names:
          - open-health-exchange
      relabel_configs:
      - source_labels: [__meta_kubernetes_pod_label_app]
        action: keep
        regex: ohe-worker

    - job_name: 'redis'
      static_configs:
      - targets: ['redis-cluster:6379']

    - job_name: 'postgres'
      static_configs:
      - targets: ['postgres-primary:5432']

  alert_rules.yml: |
    groups:
    - name: ohe-alerts
      rules:
      - alert: HighErrorRate
        expr: rate(http_requests_total{status=~"5.."}[5m]) > 0.1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High error rate detected"
          description: "Error rate is {{ $value }} errors per second"

      - alert: HighResponseTime
        expr: histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High response time detected"
          description: "95th percentile response time is {{ $value }}s"

      - alert: RedisDown
        expr: up{job="redis"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Redis is down"
          description: "Redis instance {{ $labels.instance }} is down"

      - alert: PostgresDown
        expr: up{job="postgres"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL is down"
          description: "PostgreSQL instance {{ $labels.instance }} is down"

      - alert: HighMemoryUsage
        expr: (container_memory_usage_bytes / container_spec_memory_limit_bytes) > 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High memory usage"
          description: "Container {{ $labels.container }} memory usage is {{ $value }}%"
```

### Grafana Dashboard

```yaml
# grafana.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: open-health-exchange
spec:
  replicas: 1
  selector:
    matchLabels:
      app: grafana
  template:
    metadata:
      labels:
        app: grafana
    spec:
      containers:
      - name: grafana
        image: grafana/grafana:latest
        ports:
        - containerPort: 3000
        env:
        - name: GF_SECURITY_ADMIN_PASSWORD
          valueFrom:
            secretKeyRef:
              name: grafana-secrets
              key: admin-password
        - name: GF_INSTALL_PLUGINS
          value: "grafana-kubernetes-app"
        volumeMounts:
        - name: grafana-storage
          mountPath: /var/lib/grafana
        - name: grafana-config
          mountPath: /etc/grafana/provisioning
      volumes:
      - name: grafana-storage
        persistentVolumeClaim:
          claimName: grafana-storage
      - name: grafana-config
        configMap:
          name: grafana-config
```

## Security Configuration

### Network Policies

```yaml
# network-policy.yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: ohe-network-policy
  namespace: open-health-exchange
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          name: ingress-nginx
    ports:
    - protocol: TCP
      port: 8000
  - from:
    - namespaceSelector:
        matchLabels:
          name: monitoring
    ports:
    - protocol: TCP
      port: 8000
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - protocol: TCP
      port: 5432
  - to:
    - podSelector:
        matchLabels:
          app: redis-cluster
    ports:
    - protocol: TCP
      port: 6379
  - to: []
    ports:
    - protocol: TCP
      port: 443
    - protocol: TCP
      port: 80
    - protocol: UDP
      port: 53
```

### Pod Security Standards

```yaml
# pod-security-policy.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: ohe-service-account
  namespace: open-health-exchange

---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: ohe-role
  namespace: open-health-exchange
rules:
- apiGroups: [""]
  resources: ["configmaps", "secrets"]
  verbs: ["get", "list"]

---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: ohe-role-binding
  namespace: open-health-exchange
subjects:
- kind: ServiceAccount
  name: ohe-service-account
  namespace: open-health-exchange
roleRef:
  kind: Role
  name: ohe-role
  apiGroup: rbac.authorization.k8s.io
```

## Deployment Process

### CI/CD Pipeline

```mermaid
graph LR
    subgraph "Development"
        CODE[Code Changes]
        PR[Pull Request]
        TEST[Automated Tests]
    end

    subgraph "Build"
        BUILD[Docker Build]
        SCAN[Security Scan]
        PUSH[Push to Registry]
    end

    subgraph "Deployment"
        STAGING[Staging Deploy]
        SMOKE[Smoke Tests]
        PROD[Production Deploy]
        MONITOR[Monitor & Validate]
    end

    CODE --> PR
    PR --> TEST
    TEST --> BUILD
    BUILD --> SCAN
    SCAN --> PUSH
    PUSH --> STAGING
    STAGING --> SMOKE
    SMOKE --> PROD
    PROD --> MONITOR
```

### Deployment Commands

```bash
# 1. Create namespace and apply configurations
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/secrets.yaml

# 2. Deploy data layer
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis-cluster.yaml

# 3. Wait for data layer to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n open-health-exchange --timeout=300s
kubectl wait --for=condition=ready pod -l app=redis-cluster -n open-health-exchange --timeout=300s

# 4. Run database migrations
kubectl apply -f k8s/migration-job.yaml
kubectl wait --for=condition=complete job/django-migrate -n open-health-exchange --timeout=300s

# 5. Deploy application
kubectl apply -f k8s/deployment-web.yaml
kubectl apply -f k8s/deployment-worker.yaml
kubectl apply -f k8s/service.yaml

# 6. Setup ingress and networking
kubectl apply -f k8s/ingress.yaml
kubectl apply -f k8s/network-policy.yaml

# 7. Deploy monitoring
kubectl apply -f k8s/prometheus.yaml
kubectl apply -f k8s/grafana.yaml

# 8. Setup autoscaling
kubectl apply -f k8s/hpa.yaml

# 9. Verify deployment
kubectl get pods -n open-health-exchange
kubectl get services -n open-health-exchange
kubectl get ingress -n open-health-exchange
```

### Rolling Updates

```bash
# Update application image
kubectl set image deployment/ohe-web web=open-health-exchange/web:v2.1.0 -n open-health-exchange
kubectl set image deployment/ohe-worker worker=open-health-exchange/worker:v2.1.0 -n open-health-exchange

# Monitor rollout
kubectl rollout status deployment/ohe-web -n open-health-exchange
kubectl rollout status deployment/ohe-worker -n open-health-exchange

# Rollback if needed
kubectl rollout undo deployment/ohe-web -n open-health-exchange
```

## Backup and Disaster Recovery

### Database Backup

```yaml
# backup-cronjob.yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: postgres-backup
  namespace: open-health-exchange
spec:
  schedule: "0 2 * * *"  # Daily at 2 AM
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: postgres-backup
            image: postgres:15-alpine
            command:
            - /bin/bash
            - -c
            - |
              PGPASSWORD=$POSTGRES_PASSWORD pg_dump -h postgres-primary -U ohe_user -d open_health_exchange > /backup/backup-$(date +%Y%m%d-%H%M%S).sql
              # Upload to S3 or other storage
              aws s3 cp /backup/backup-$(date +%Y%m%d-%H%M%S).sql s3://ohe-backups/
            env:
            - name: POSTGRES_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: ohe-secrets
                  key: DB_PASSWORD
            volumeMounts:
            - name: backup-storage
              mountPath: /backup
          volumes:
          - name: backup-storage
            emptyDir: {}
          restartPolicy: OnFailure
```

### Monitoring Alerts Configuration

```yaml
# alertmanager-config.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config
  namespace: open-health-exchange
data:
  alertmanager.yml: |
    global:
      smtp_smarthost: 'localhost:587'
      smtp_from: 'alerts@open-health-exchange.org'

    route:
      group_by: ['alertname']
      group_wait: 10s
      group_interval: 10s
      repeat_interval: 1h
      receiver: 'web.hook'

    receivers:
    - name: 'web.hook'
      email_configs:
      - to: 'ops-team@open-health-exchange.org'
        subject: 'OHE Alert: {{ .GroupLabels.alertname }}'
        body: |
          {{ range .Alerts }}
          Alert: {{ .Annotations.summary }}
          Description: {{ .Annotations.description }}
          {{ end }}

      slack_configs:
      - api_url: 'https://hooks.slack.com/services/YOUR/SLACK/WEBHOOK'
        channel: '#ops-alerts'
        title: 'OHE Alert: {{ .GroupLabels.alertname }}'
        text: |
          {{ range .Alerts }}
          {{ .Annotations.summary }}
          {{ .Annotations.description }}
          {{ end }}

    inhibit_rules:
    - source_match:
        severity: 'critical'
      target_match:
        severity: 'warning'
      equal: ['alertname', 'instance']
```

This deployment guide provides a comprehensive production-ready setup for Open Health Exchange with high availability, monitoring, security, and scalability built-in from the start.

## Deployment Topology Options

| Topology | When to Use | Valkey / Redis | PostgreSQL | Trade-offs |
|----------|-------------|----------------|-----------|-----------|
| Single Node (Dev) | Local dev / CI | Container / ephemeral | Container / ephemeral | Simplest, no HA |
| Managed Standard | Baseline prod | Managed instance (Memorystore Basic / AWS ElastiCache single AZ) | Managed single instance (Cloud SQL / RDS) | Minimal ops, limited failover |
| Managed HA | Production SLOs | Memorystore Standard / Multi-AZ ElastiCache | Cloud SQL HA / RDS Multi-AZ | Higher cost, automatic failover |
| Clustered Cache | High write concurrency | Sharded Redis/Valkey cluster | Managed HA | Operational complexity |
| Multi-Region (Active/Passive) | DR + latency | Regional replica (read-only) | Cross-region replica | Failover runbook needed |
| Multi-Region (Active/Active)* | Lowest latency + resilience | Global routing + conflict mgmt | Logical write partitioning | *Complex consistency model* |

## GCP Service Mapping (Example)

| Concern | GCP Service | Notes |
|--------|-------------|-------|
| PostgreSQL | Cloud SQL for PostgreSQL | Enable automated backups + PITR |
| Valkey/Redis | Memorystore (Standard Tier) | Choose size for peak queue + cache footprint |
| Metrics Scrape | Managed Prometheus (GKE) | Use PodMonitor for `/api/metrics/metrics/` |
| Logs | Cloud Logging | Consider structured JSON via LOG_JSON=true |
| Secrets | Secret Manager | Sync to Kubernetes via CSI driver |
| Certificates | cert-manager + CloudDNS | Automate ACME issuance |
| Ingress | GKE Ingress / Cloud Load Balancing | Terminate TLS at LB |

### Example Environment Variable Patterns

```
DATABASE_URL=postgresql://ohe_user:${DB_PASSWORD}@/cloudsql/${CLOUDSQL_INSTANCE}/open_health_exchange
REDIS_URL=redis://memorystore-host:6379/0
REDIS_CACHE_URL=redis://memorystore-host:6379/1
```

Where `CLOUDSQL_INSTANCE` may be `project:region:instance` when using the Cloud SQL Auth proxy sidecar.

## Connection & Resource Sizing Guidelines

### PostgreSQL
| Aspect | Guideline |
|--------|-----------|
| Max Connections | Use a pooler (PgBouncer) if > 50 concurrent workers |
| CPU | Start at 2 vCPU / 4 GB for production pilot |
| Autovacuum | Keep defaults; monitor bloat quarterly |
| Backups | Enable PITR; test restore quarterly |

### Valkey / Redis
| Aspect | Guideline |
|--------|-----------|
| Memory Headroom | Allocate 2x peak observed usage (queue + cache) |
| Eviction Policy | `allkeys-lru` if cache heavy; default if minimal caching |
| Persistence | Disable RDB/AOF for pure queue to reduce latency |
| Latency Target | < 5 ms P99 for queue ops |

### Huey Workers
| Aspect | Guideline |
|--------|-----------|
| Concurrency | Start 1 worker process per CPU core (threads vs processes based on blocking I/O) |
| Task Duration | Keep under 10s; long operations chunked |
| Retries | Implement idempotency for safe re-execution |

### Django Web Pods
| Aspect | Guideline |
|--------|-----------|
| Gunicorn Workers (if used) | `(2 x CPU) + 1` rule of thumb |
| Memory | 512Mi baseline; watch RSS and tune |
| Health Probes | Keep readiness lightweight (<100ms) |

### Capacity Planning Quick Start
1. Measure average webhook rate per provider.
2. Determine peak burst factor (often 3–5x average).
3. Size Huey workers to drain peak burst within SLA window (e.g., 1 min).
4. Set HPA CPU target ~70% to allow burst headroom.
5. Revisit sizing monthly for first 3 months of production.

## Operational Runbooks (Starter)

| Scenario | Action |
|----------|--------|
| Redis latency spike | Check network, memory fragmentation, slow log; scale vertically/horizontally |
| Queue backlog growth | Add Huey worker replicas; profile slow tasks |
| FHIR server errors | Triage error classification logs; apply backoff adjustments |
| Unexpected 5xx rate | Inspect structured logs by correlation ID (when implemented) |
| Elevated task retries | Check provider status pages; apply temporary throttling |

## Glossary (Excerpt)
| Term | Definition |
|------|------------|
| Provider Link | Association of EHR user to external provider account |
| Sync Operation | Background task fetching + transforming provider data |
| FHIR Publish | POST/PUT of generated FHIR resources to target server |
| Backlog Depth | Count of pending Huey tasks in queue |