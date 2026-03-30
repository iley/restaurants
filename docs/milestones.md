# Restaurant Tracker: Milestones

## M1: Project skeleton + data model + admin

- Initialize Django project, configure settings (SQLite, static files)
- Define models: City, Restaurant (name, location, cuisine, venue category, Michelin status, rating, comments), Visit (date, notes), Photo
- Set up Django admin with useful list displays, filters, and search
- **Validate:** add a handful of real restaurants through the admin, verify the data model feels right

## M2: Public list view

- Restaurant list page for the selected city
- Table/list layout showing name, cuisine, venue category, rating tier, Michelin status
- City selector as top-level partition
- Style with Bulma (no build step)
- **Validate:** browse restaurants in a browser, check it looks decent on mobile

## M3: Filtering with HTMX

- Add filter controls: cuisine type, venue category, Michelin status, rating tier
- HTMX partial updates -- filters work without full page reloads
- **Validate:** filter combinations work, URL is shareable/bookmarkable

## M4: Load existing data

- Load pre-existing data from the CSV file into the database
- Perhaps use Django fixtures (evaluate alternative options)

## M5: Detail view + photos

- Restaurant detail page: all fields, visit history, photos
- Photo upload through Django admin, display on detail page
- **Validate:** click through from list to detail, see photos, check it reads well

## M6: Google Places integration

- Auto-fill address, website, and Google Maps link when adding a restaurant in the admin
- **Validate:** add a new restaurant, confirm Places data populates correctly
- Add a way to re-populate data for existing entries (in admin if easy to do so, otherwise in CLI)

## M7: Deployment

- Dockerfile + docker-compose (app + static/media file serving)
- Deploy to a single VPS, SQLite on a mounted volume
- **Validate:** app running on a real URL
