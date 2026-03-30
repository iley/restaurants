# Progress

## Current milestone: M5 — Sorting

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
- [ ] Validate: sort interactions work correctly, URL is shareable

## To do

### M6: Deployment

- [ ] Dockerfile + docker-compose
- [ ] Deploy to VPS, SQLite on mounted volume
- [ ] Validate: app running on a real URL

### M7: Detail view + photos

- [ ] Restaurant detail page: all fields, visit history, photos
- [ ] Photo upload through Django admin, display on detail page
- [ ] Validate: click through from list to detail, photos display well

### M8: Google Places integration

- [ ] Auto-fill address, website, and Google Maps link in admin
- [ ] Validate: add a new restaurant, confirm Places data populates
