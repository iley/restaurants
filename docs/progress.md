# Progress

## Current milestone: M4 — Load existing data

## Completed

### M1: Project skeleton + data model + admin

- [x] Django project initialized (`config/` project, `restaurants/` app)
- [x] Models: City, Restaurant, Visit, Photo
- [x] Django admin with filters, search, and inline Visit/Photo editing
- [x] Settings configured (SQLite, media files for photo uploads)
- [x] Validate: add real restaurants through the admin, verify data model feels right

### M2: Public list view

- [x] Restaurant list page for the selected city
- [x] Table/list layout showing name, cuisine, venue category, rating tier, Michelin status
- [x] City selector as dropdown in navbar
- [x] Style with Bulma (vendored, no CDN or build step)
- [x] Validate: browse restaurants in a browser, check mobile

### M3: Filtering with HTMX

- [x] Filter controls: cuisine type, venue category, Michelin status, rating tier
- [x] HTMX partial updates (no full page reloads)
- [x] Validate: filter combinations work, URL is shareable/bookmarkable

## To do

### M4: Load existing data

- [ ] Load pre-existing data from CSV into the database
- [ ] Evaluate approach (Django fixtures vs alternatives)

### M5: Detail view + photos

- [ ] Restaurant detail page: all fields, visit history, photos
- [ ] Photo upload through Django admin, display on detail page
- [ ] Validate: click through from list to detail, photos display well

### M6: Google Places integration

- [ ] Auto-fill address, website, and Google Maps link in admin
- [ ] Validate: add a new restaurant, confirm Places data populates

### M7: Deployment

- [ ] Dockerfile + docker-compose
- [ ] Deploy to VPS, SQLite on mounted volume
- [ ] Validate: app running on a real URL
