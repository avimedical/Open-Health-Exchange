# Open Health Exchange

This repository provides a Django-based service to synchronize device data to FHIR systems. Below are containerization and CI details.

## Container image (Podman)

Build a local image:

```bash
podman build -t open-health-exchange:dev .
```

Run the web server from the image:

```bash
podman run --rm -p 8000:8000 \
  -e DJANGO_SETTINGS_MODULE=open_health_exchange.settings \
  -e DATABASE_URL=postgres://postgres:postgres@host.containers.internal:5432/postgres \
  -e REDIS_URL=redis://host.containers.internal:6379/0 \
  -e REDIS_CACHE_URL=redis://host.containers.internal:6379/1 \
  open-health-exchange:dev
```

Run the Huey worker from the same image (different command):

```bash
podman run --rm \
  -e DJANGO_SETTINGS_MODULE=open_health_exchange.settings \
  -e DATABASE_URL=postgres://postgres:postgres@host.containers.internal:5432/postgres \
  -e REDIS_URL=redis://host.containers.internal:6379/0 \
  -e REDIS_CACHE_URL=redis://host.containers.internal:6379/1 \
  open-health-exchange:dev \
  python manage.py run_huey -V --workers 1 --worker-type thread
```

## Podman Compose (local dev)

A `docker-compose.yml` is provided to orchestrate the app with Valkey and Postgres. It also works with Podman’s compose.

```bash
# Build images and start the stack
podman compose up --build

# Stop and remove
podman compose down
```

Services:
- web: Django dev server on :8000
- huey: Huey consumer using the same image
- valkey: Valkey 8.x
- postgres: PostgreSQL 17

## CI/CD

GitHub Actions are configured to:
- Run lint (flake8) and tests (pytest) on pull requests to `main`
- Build the Docker image on PRs (no push)
- Build and push to GHCR on `main` pushes

Image name:
- `ghcr.io/<owner>/open-health-exchange` (lowercase)

Poetry 2.2.x is used in CI and the Dockerfile. Tests are executed with real Valkey and Postgres services.
