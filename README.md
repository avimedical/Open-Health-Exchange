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
- Run lint (ruff) and tests (pytest) on pull requests to `main`
- Build the Docker image on PRs (no push)
- Build and push to GHCR on `main` pushes

Image name:
- `ghcr.io/<owner>/open-health-exchange` (lowercase)

Poetry 2.2.x is used in CI and the Dockerfile. Tests are executed with real Valkey and Postgres services.

## Development Guidelines

### Commit Message Format

This project uses [Conventional Commits](https://www.conventionalcommits.org/) for consistent commit messages. Commit messages are automatically validated via pre-commit hooks.

**Format:**
```
<type>: <description>

[optional body]

[optional footer]
```

**Allowed commit types:**
- `feat:` - A new feature
- `fix:` - A bug fix (including hotfixes)
- `docs:` - Documentation only changes
- `style:` - Changes that don't affect code meaning (formatting, etc.)
- `refactor:` - Code change that neither fixes a bug nor adds a feature
- `perf:` - Performance improvement
- `test:` - Adding missing tests or correcting existing tests
- `build:` - Changes to build system or dependencies
- `ci:` - Changes to CI configuration files and scripts
- `chore:` - Other changes that don't modify src or test files
- `revert:` - Reverts a previous commit

**Examples:**
```bash
git commit -m "feat: add Withings OAuth integration"
git commit -m "fix: resolve timezone handling in ECG transformer"
git commit -m "refactor: update FHIR client initialization"
git commit -m "docs: add commit message guidelines to README"
git commit -m "chore: setup pre-commit hooks"
```

### Pre-commit Hooks

Pre-commit hooks are configured to run automatically before each commit:
- **Ruff linting** with auto-fix
- **Ruff formatting** for consistent code style
- **Commit message validation** (Conventional Commits)
- **File checks** (large files, merge conflicts, trailing whitespace, etc.)

**First-time setup:**
```bash
poetry install
poetry run pre-commit install
poetry run pre-commit install --hook-type commit-msg
```

**Manual execution:**
```bash
# Run all hooks on all files
poetry run pre-commit run --all-files

# Run hooks on staged files only
poetry run pre-commit run
```

**Bypass hooks (use sparingly):**
```bash
git commit --no-verify -m "fix: emergency hotfix"
```
