<!--
Thanks for contributing to Open Health Exchange!

Please fill out the sections below so reviewers can evaluate your change quickly.
Lines inside HTML comments (like this one) are hidden when the PR is submitted,
so you can keep them for guidance or remove them — your choice.
-->

## Summary

<!-- What does this PR do, and why? One or two short paragraphs. -->

## Related Issues

<!--
Link any issues this PR addresses. Use GitHub keywords to auto-close on merge:
  Closes #123
  Fixes #456
  Refs #789
-->

## Type of Change

<!-- Check all that apply with an `x` (no spaces: [x]). -->

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would change existing behavior)
- [ ] Refactor / code cleanup (no functional change)
- [ ] Documentation update
- [ ] Build, CI, or tooling change
- [ ] Performance improvement
- [ ] Security fix

## Changes

<!--
Bullet the notable changes so reviewers can orient themselves before reading the diff.
Mention new/removed endpoints, models, migrations, background tasks, env vars, etc.
-->

-
-

## How Has This Been Tested?

<!--
Describe the tests you ran and how reviewers can reproduce them locally.
Include relevant commands, fixtures, or test data. Example:

    poetry run ruff check .
    poetry run ruff format --check .
    poetry run mypy .
    poetry run pytest
-->

- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `mypy .` passes
- [ ] Unit tests added/updated and passing (`pytest`)
- [ ] Manually tested the affected flow (describe below)

**Manual test notes:**

<!-- e.g. "Linked a Withings account via /api/base/link/withings/ and verified webhook delivery." -->

## Database & Migrations

<!-- Remove this section if not applicable. -->

- [ ] This PR includes new migrations (`python manage.py makemigrations`)
- [ ] Migrations are backward-compatible / safe to roll back
- [ ] No destructive operations on existing data (or called out below)

## Configuration & Deployment

<!-- Remove this section if not applicable. -->

- [ ] New or changed environment variables are documented in `.env.example` and the README
- [ ] New dependencies are added to `pyproject.toml` and locked with Poetry
- [ ] Changes are backward-compatible with existing deployments
- [ ] Breaking changes are called out in the summary above

## FHIR / Health Data Impact

<!-- Remove this section if your change does not touch FHIR resources, provider integrations, or data flow. -->

- [ ] New/changed FHIR R5 resources conform to the R5 spec
- [ ] Provider integrations (Withings, Fitbit, …) were tested against real or recorded responses
- [ ] No PHI / personal health data is logged or persisted (service remains pass-through)
- [ ] All datetimes are timezone-aware and stored/serialized in UTC (see `CLAUDE.md`)

## Security & Privacy

- [ ] I have not committed secrets, tokens, or credentials
- [ ] Input from users / webhooks is validated
- [ ] Webhook signature verification is preserved or updated appropriately
- [ ] Authentication and authorization checks are preserved

## Screenshots / Logs

<!-- Optional: attach screenshots, curl examples, log snippets, or Prometheus metrics that show the change working. -->

## Checklist

- [ ] I have read the project's `README.md` and `CLAUDE.md`
- [ ] My code follows the existing style (enforced by `ruff`)
- [ ] I have added or updated tests that prove my fix is effective or my feature works
- [ ] I have updated documentation where needed (README, `docs/`, docstrings)
- [ ] My commit messages are clear and follow conventional style (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)
- [ ] I have rebased onto the latest `main` and resolved any conflicts
- [ ] I agree that my contribution is licensed under this project's `LICENSE`

## Additional Notes for Reviewers

<!-- Anything else that would help the reviewer: tradeoffs considered, follow-up work, known limitations. -->
