# Restaurant Tracker

Personal web app for tracking restaurants I've visited. Browse, filter, and share recommendations.

Stack: Django, HTMX, Bulma, SQLite. Deployed via Docker on a single EC2 instance.

## Development

```bash
uv run manage.py runserver       # dev server at localhost:8000
uv run manage.py makemigrations  # after model changes
uv run manage.py migrate         # apply migrations
```

### Attribute fetching

External lookups go through a small abstraction in `restaurants/sources.py`: each source is a callable `(Probe) -> dict | None`, registered in the `SOURCES` list. `fetch_all` merges results field by field, with the first source returning a non-empty value winning.

In the admin add/change form, click the **Fetch attributes** button after entering a name and city. A panel appears showing each fetchable field as current vs proposed; click **Apply** on a row (or **Apply all**) to fill the form input, then review and Save normally. Saves never trigger an automatic fetch — every value comes from an explicit click. The button consults all registered sources (Google Places + Michelin).

Bulk command for live external sources (Google Places only — Michelin is handled separately, see below):

```bash
uv run manage.py fetch_all_data              # backfill restaurants missing any live-source field
uv run manage.py fetch_all_data --city dublin # only a specific city
uv run manage.py fetch_all_data --force       # overwrite existing data with fresh API values
uv run manage.py fetch_all_data --all         # include all restaurants, not just those missing data
```

`michelin_status` is intentionally not part of `fetch_all_data` because Michelin updates are infrequent and reviewed separately — see the Michelin section below.

#### Google Places only

Fills address, website, Google Maps link, and Google rating from the Google Places API. Requires `GOOGLE_PLACES_API_KEY` environment variable (set in `ansible/secrets.yml` for production).

```bash
uv run manage.py fetch_google_places_data              # backfill restaurants missing any Places field
uv run manage.py fetch_google_places_data --city dublin # only a specific city
uv run manage.py fetch_google_places_data --force       # overwrite existing data with fresh API values
uv run manage.py fetch_google_places_data --all         # include all restaurants, not just those missing data
```

Also available as admin actions: "Fetch Google Places data" (backfill) and "Re-fetch Google Places data (overwrite)".

### Michelin guide integration

Fills `michelin_status` from a local copy of the Michelin guide CSV. Matching is fuzzy (handles accents, capitalization, and missing words like "Bloom" vs "Bloom Brasserie") with lat/lon proximity as a tiebreaker.

Data source: download `michelin_my_maps.csv` from [the Kaggle Michelin guide dataset](https://www.kaggle.com/datasets/ngshiheng/michelin-guide-restaurants-2021) and place it at `data/michelin_my_maps.csv`. The file is gitignored. Credits to the dataset author and Michelin.

The path is configurable via the `MICHELIN_CSV_PATH` env var (default: `data/michelin_my_maps.csv` relative to the project root). In production the container bind-mounts the host CSV at `/app/data/michelin_my_maps.csv` and sets the env var accordingly.

Local refresh:

```bash
# 1. Re-download the CSV from Kaggle, replace data/michelin_my_maps.csv.
# 2. Review the diff (dry-run by default):
uv run manage.py update_michelin_data
uv run manage.py update_michelin_data --city dublin  # scope to one city
# 3. Apply the changes:
uv run manage.py update_michelin_data --apply
```

The diff prints one line per restaurant: `no change`, `WOULD CHANGE: <current> → <proposed>`, or `no CSV match` (useful for spotting demotions — manually fix these).

Production refresh: replace the local CSV, then `./deploy.sh` (Ansible uploads the CSV iff it changed; no container restart). Then SSH and apply against the prod DB:

```bash
ssh ubuntu@<elastic-ip>
sudo docker exec -it restaurants python manage.py update_michelin_data           # review
sudo docker exec -it restaurants python manage.py update_michelin_data --apply   # apply
```

Also available as admin actions: "Update Michelin status" (skip rows whose status is already set) and "Re-fetch Michelin status (overwrite)".

#### Adding another source

To add a new source, implement a `(Probe) -> dict | None` callable in `restaurants/`, append it to `SOURCES` in `sources.py`, and extend `FETCHABLE_FIELDS` if it surfaces new columns — the admin button picks it up automatically. If the source should also run in `fetch_all_data`, add it to `LIVE_SOURCES` too.

### Thumbnails

Thumbnails are generated automatically on photo upload. To generate thumbnails for existing photos:

```bash
uv run manage.py generate_thumbnails         # only photos missing a thumbnail
uv run manage.py generate_thumbnails --force  # regenerate all thumbnails
```

### EXIF stripping

EXIF metadata (GPS location, timestamps, etc.) is automatically stripped from photos on upload. To strip metadata from previously uploaded photos:

```bash
uv run manage.py strip_exif
```

## Deployment

### Architecture

Cloudflare (SSL) -> Elastic IP -> nginx (host) -> Docker container (gunicorn + Django)

Data (SQLite DB, media, static files) lives on a separate EBS volume at `/opt/restaurants/`.

### Prerequisites

- Terraform >= 1.0
- uv (for running Ansible)
- AWS CLI configured with credentials
- An SSH key pair in AWS

### Provision infrastructure

```bash
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your key_name
terraform init
terraform apply
```

Point your domain's A record to the elastic IP in Cloudflare (proxied). Flexible SSL mode works because nginx hardcodes `X-Forwarded-Proto: https` so Django sees the correct scheme regardless of the origin-side connection.

### Deploy the application

First-time setup:

```bash
# 1. Create inventory with your server's IP and SSH key
cp ansible/inventory.ini.example ansible/inventory.ini
# Edit ansible/inventory.ini with the correct host and SSH key path

# 2. Create secrets file (pick one)
cp ansible/secrets.yml.example ansible/secrets.yml
# Edit ansible/secrets.yml — generate a random django_secret_key and add your Google Places API key
# OR: skip this step and deploy.sh will generate one with a random Django key (but no Places key)
```

Then deploy:

```bash
./deploy.sh
```

Both `ansible/inventory.ini` and `ansible/secrets.yml` are gitignored.

### Routine deploys

Push to `main` -- GitHub Actions builds and pushes the Docker image to GHCR. Then re-run:

```bash
./deploy.sh
```

### First-time setup on the server

```bash
# Copy your local database to the server
scp db.sqlite3 ubuntu@<elastic-ip>:~/db.sqlite3
ssh ubuntu@<elastic-ip> "sudo mv ~/db.sqlite3 /opt/restaurants/db.sqlite3 && sudo systemctl restart restaurants"

# Create a superuser
ssh ubuntu@<elastic-ip>
sudo docker exec -it restaurants python manage.py createsuperuser
```

### Running admin commands on the server

SSH into the server and use `docker exec` to run Django management commands inside the running container:

```bash
ssh ubuntu@<elastic-ip>
sudo docker exec -it restaurants python manage.py <command>
```
