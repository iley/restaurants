# Restaurant Tracker

Personal web app for tracking restaurants I've visited. Browse, filter, and share recommendations.

Stack: Django, HTMX, Bulma, SQLite. Deployed via Docker on a single EC2 instance.

## Development

```bash
uv run manage.py runserver       # dev server at localhost:8000
uv run manage.py makemigrations  # after model changes
uv run manage.py migrate         # apply migrations
```

### Google Places integration

Auto-fills address, website, Google Maps link, and Google rating from the Google Places API. Requires `GOOGLE_PLACES_API_KEY` environment variable (set in `ansible/secrets.yml` for production).

```bash
uv run manage.py fetch_places_data              # backfill restaurants missing any Places field
uv run manage.py fetch_places_data --city dublin # only a specific city
uv run manage.py fetch_places_data --force       # overwrite existing data with fresh API values
uv run manage.py fetch_places_data --all         # include all restaurants, not just those missing data
```

Also available as admin actions: "Fetch Google Places data" (backfill) and "Re-fetch Google Places data (overwrite)".

New restaurants are automatically enriched on save when the API key is configured.

### Thumbnails

Thumbnails are generated automatically on photo upload. To generate thumbnails for existing photos:

```bash
uv run manage.py generate_thumbnails         # only photos missing a thumbnail
uv run manage.py generate_thumbnails --force  # regenerate all thumbnails
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
scp db.sqlite3 ec2-user@<elastic-ip>:~/db.sqlite3
ssh ec2-user@<elastic-ip> "sudo mv ~/db.sqlite3 /opt/restaurants/db.sqlite3 && sudo systemctl restart restaurants"

# Create a superuser
ssh ec2-user@<elastic-ip>
sudo docker exec -it restaurants python manage.py createsuperuser
```

### Running admin commands on the server

SSH into the server and use `docker exec` to run Django management commands inside the running container:

```bash
ssh ec2-user@<elastic-ip>
sudo docker exec -it restaurants python manage.py <command>
```
