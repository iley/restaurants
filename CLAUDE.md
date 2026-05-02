# Restaurant Tracker

Personal web app replacing a Google Sheets spreadsheet for tracking restaurants I've visited. Browse, filter, and share recommendations -- with photos and without the clunkiness of a spreadsheet.

Stack: Django, HTMX, Bulma, SQLite. Deployed via Docker on a single VPS.

## Docs

- [README.md](README.md) -- developer/user-facing documentation (commands, deployment, features)
- [docs/proposal.md](docs/proposal.md) -- requirements, data model, technical decisions
- [docs/milestones.md](docs/milestones.md) -- implementation breakdown
- [docs/progress.md](docs/progress.md) -- current progress and remaining work

## Development

```bash
uv run manage.py runserver       # start dev server at localhost:8000
uv run manage.py makemigrations  # after model changes
uv run manage.py migrate         # apply migrations
uv run manage.py createsuperuser # create admin user
uv run manage.py shell           # interactive Django shell
uv add <package>                 # add a dependency
```

### Attribute fetching

Sources are `(Probe) -> dict | None` callables registered in `restaurants/sources.py`.
`SOURCES` is the full list (used by the admin Fetch attributes button); `LIVE_SOURCES`
is the subset safe to run in bulk (Google Places only — Michelin is reviewed
separately). `FETCHABLE_FIELDS` is the shared whitelist.

```bash
uv run manage.py fetch_all_data            # bulk backfill across LIVE_SOURCES
uv run manage.py fetch_google_places_data  # Google Places only (renamed from fetch_places_data)
uv run manage.py update_michelin_data      # Michelin diff; --apply to write
```

Each command supports `--city <slug>`, `--force`, and `--all` (except
`update_michelin_data`, which uses `--city` and `--apply`). Google Places
commands require `GOOGLE_PLACES_API_KEY`. The Michelin CSV path is configurable
via `MICHELIN_CSV_PATH` (defaults to `data/michelin_my_maps.csv`); the file is
gitignored and uploaded by Ansible.

Tests live in `restaurants/tests/` (a package): `test_main.py`,
`test_michelin.py`, and `fixtures/`. Run with `uv run manage.py test restaurants`.

### Deployment

```bash
./deploy.sh                      # deploy to VPS (creates ansible/secrets.yml on first run)
```

Secrets live in `ansible/secrets.yml` (gitignored). See `ansible/secrets.yml.example` for the format.
