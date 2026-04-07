# Restaurant Tracker: Proposal

## Background

I currently track restaurants I've visited in a Google Sheets spreadsheet. For each restaurant I record:

- Name
- Category (type of cuisine)
- Location (neighbourhood or area)
- Personal rating out of 10
- Michelin awards (Bib Gourmand, stars, "Michelin Selected")
- Whether I've been more than once
- Date visited
- Free-text comments

The data is split across sheets by venue type (e.g. a separate sheet for sandwich places). Right now the spreadsheet only covers Dublin (~130 entries), but I'd like to maintain separate lists for other cities too.

I use the data in three ways:

1. **Revisiting**: scan the list and think "I haven't been to Grano in a while, I should book a table."
2. **Recommending**: when someone asks "what's a good Italian restaurant?", quickly filter to high-rated Italian places.
3. **Exploring gaps**: browse and notice "I haven't tried any Brazilian restaurant, I should fix that."

The spreadsheet works but is clunky to filter, has no photos, and doesn't lend itself to quick lookups on a phone.

## Goal

Build a simple web app that replaces the spreadsheet. It should make it faster to browse, filter, and share restaurant recommendations — without requiring me to manually enter every detail about each place.

## Requirements

### Data model

- Each restaurant belongs to a **city** (Dublin, etc.). Cities act as top-level partitions; browsing always happens within one city.
- A restaurant has: name, location/neighbourhood, cuisine type, venue category (restaurant, cafe, sandwich place, pub, etc.), Michelin status, personal rating (1-10, internal), comments, and photos.
- **Visits** are tracked separately — each visit has a date and optional notes. This replaces the old single "date visited" / "been more than once" fields.
- Some restaurants have multiple locations (e.g. "Bunsen" appears across Dublin). The app should handle this gracefully — likely as a single entry with a note, not one entry per branch.

### Public-facing views

1. **Restaurant list** — the main page. Shows restaurants for the selected city, filterable by:
   - City (top-level selector)
   - Venue category
   - Cuisine type
   - Michelin status
   - Rating tier
   - List/table layout. Card layout may be added in a future version.
2. **Restaurant detail** — full info about a single restaurant including photos.

### Rating display

Internally I rate 1-10, but the public-facing UI shows a simplified four-tier scale to avoid debates:

| Internal rating | Display tier        |
|-----------------|---------------------|
| 9-10            | Highly recommend    |
| 7-8             | Recommend           |
| 5-6             | It's OK             |
| 1-4             | Don't recommend     |

The numeric rating is only visible in the admin.

### Data entry

- Use Django's built-in admin for creating and editing restaurants. No need for a custom entry form in v1.
- Photo upload through admin.

### Non-goals (for v1)

- Restaurants I want to visit -- likely to be included in v2.
- Multi-user / accounts / authentication on the public side.
- Social features (comments, shared lists).
- Mobile app —  responsive web is enough.

## Technical Decisions

| Area       | Choice                          | Rationale                                                                 |
|------------|---------------------------------|---------------------------------------------------------------------------|
| Backend    | Python + Django                 | Built-in admin, ORM, migrations. Familiar and fast to ship.              |
| Frontend   | HTMX + Bulma                   | Minimal JS, server-rendered HTML. HTMX handles filtering without full page reloads. Bulma gives clean CSS with no build step. |
| Database   | SQLite                          | Simple, zero-config. Good enough for a single-user app on one server.    |
| Deployment | Single VPS + Docker             | Dockerized app on a single VPS. Simple to deploy and maintain. SQLite file lives on a mounted volume. |
| Photos     | Django file storage (initially) | Store on disk (Docker volume). Keep it simple for now.                   |
| External data | Google Places API            | Auto-fill address, website, and Google Maps link when adding a restaurant. Cost is acceptable for single-user scale. |

## Open Questions

None at this time.
