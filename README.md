# Restaurant Tracker

Personal web app for tracking restaurants I've visited. Browse, filter, and share recommendations.

Stack: Django, HTMX, Bulma, SQLite. Deployed via Docker on a single EC2 instance.

## Development

```bash
uv run manage.py runserver       # dev server at localhost:8000
uv run manage.py makemigrations  # after model changes
uv run manage.py migrate         # apply migrations
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

```bash
cp ansible/inventory.ini.example ansible/inventory.ini
# Edit ansible/inventory.ini with the correct host and SSH key path

./deploy.sh
```

The script generates a Django secret key on first run (stored in `ansible/secret_key`, gitignored) and invokes Ansible via `uvx`.

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
