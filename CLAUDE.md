# Restaurant Tracker

Personal web app replacing a Google Sheets spreadsheet for tracking restaurants I've visited. Browse, filter, and share recommendations -- with photos and without the clunkiness of a spreadsheet.

Stack: Django, HTMX, Bulma, SQLite. Deployed via Docker on a single VPS.

## Docs

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

### Google Places integration

Requires `GOOGLE_PLACES_API_KEY` environment variable.

```bash
uv run manage.py fetch_places_data              # backfill restaurants missing any Places field
uv run manage.py fetch_places_data --city dublin # only a specific city
uv run manage.py fetch_places_data --force       # overwrite existing data with fresh API values
uv run manage.py fetch_places_data --all         # include all restaurants, not just those missing data
```

Also available as admin actions: "Fetch Google Places data" (backfill) and "Re-fetch Google Places data (overwrite)".

### Deployment

```bash
./deploy.sh                      # deploy to VPS (creates ansible/secrets.yml on first run)
```

Secrets live in `ansible/secrets.yml` (gitignored). See `ansible/secrets.yml.example` for the format.
