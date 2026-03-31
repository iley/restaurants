# Progress

## Current milestone: Validation & polish

## Completed

### M1: Project skeleton + data model + admin

- [x] Django project initialized (`config/` project, `restaurants/` app)
- [x] Models: City, Restaurant, Visit, Photo
- [x] Django admin with filters, search, and inline Visit/Photo editing
- [x] Settings configured (SQLite, media files for photo uploads)
- [x] Validate: add real restaurants through the admin, verify data model feels right

### M2: Public list view

- [x] Restaurant list page for the selected city
- [x] Table/list layout showing name, cuisine, venue category, rating, Michelin status
- [x] City selector as dropdown in navbar
- [x] Style with Bulma (vendored, no CDN or build step)
- [x] Validate: browse restaurants in a browser, check mobile

### M3: Filtering with HTMX

- [x] Filter controls: cuisine type, venue category, Michelin status, rating tier
- [x] HTMX partial updates (no full page reloads)
- [x] Validate: filter combinations work, URL is shareable/bookmarkable

### M4: Load existing data

- [x] Cleaned CSV: fixed headers, split Category into Venue category + Cuisine, normalized Michelin status values, merged "been more than once" into comments
- [x] Django management command (`import_csv`) to load CSV into the database
- [x] Validate: 131 restaurants loaded, idempotent on re-run

### M5: Sorting

- [x] Clickable table headers with ascending/descending toggle
- [x] Stable sorting: previous sort columns kept as tiebreakers
- [x] Default sort: rating descending, then name ascending
- [x] Sort state preserved in URL (shareable) and across filter changes (via OOB swap)
- [x] Validate: sort interactions work correctly, URL is shareable

### M6: Deployment

- [x] Django settings made production-ready (env vars, STATIC_ROOT, proxy headers)
- [x] Dockerfile (multi-stage build with uv + gunicorn)
- [x] GitHub Actions workflow (build arm64 image, push to GHCR)
- [x] Terraform config (EC2, security group, EIP, EBS volume)
- [x] Ansible playbook (Docker, nginx, container deployment)
- [x] Provision infrastructure and deploy
- [x] Validate: app running on restaurants.istrukov.com

### M7: Detail view + photos

- [x] Restaurant detail page: all fields, visit history, photos
- [x] Photo upload through Django admin, display on detail page
- [ ] Validate: click through from list to detail, photos display well

### M8: Google Places integration

- [x] Places API service (`restaurants/places.py`) — calls Google Places Text Search API
- [x] Auto-fill address, website, Google Maps link, and Google rating on save in admin
- [x] Admin actions: "Fetch Google Places data" (backfill) and "Re-fetch Google Places data (overwrite)"
- [x] Management command `fetch_places_data` with `--city`, `--all`, `--force` options
- [x] `google_place_id` and `google_rating` fields on Restaurant model
- [x] Centralized secrets in `ansible/secrets.yml`, deploy passes `GOOGLE_PLACES_API_KEY` to container
- [ ] Validate: add a new restaurant, confirm Places data populates
- [ ] Validate: run bulk backfill, review results
