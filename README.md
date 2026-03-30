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
- Ansible
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

Point your domain's A record to the elastic IP in Cloudflare (proxied, Flexible SSL).

### Deploy the application

```bash
cd ansible
cp inventory.ini.example inventory.ini
# Edit inventory.ini with the correct host and SSH key path

ansible-playbook -i inventory.ini playbook.yml \
  --extra-vars "django_secret_key=YOUR_SECRET_KEY"
```

### Routine deploys

Push to `main` -- GitHub Actions builds and pushes the Docker image to GHCR. Then re-run the Ansible playbook to pull and restart:

```bash
ansible-playbook -i ansible/inventory.ini ansible/playbook.yml \
  --extra-vars "django_secret_key=YOUR_SECRET_KEY"
```

### First-time setup on the server

```bash
# Copy your local database to the server
scp db.sqlite3 ec2-user@<elastic-ip>:/opt/restaurants/db.sqlite3

# Create a superuser
ssh ec2-user@<elastic-ip>
sudo docker exec -it restaurants python manage.py createsuperuser
```
