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
