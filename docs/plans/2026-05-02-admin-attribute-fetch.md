# Reviewable admin attribute fetching

## Overview
Replace the silent `RestaurantAdmin.save_model` auto-fetch with an explicit, reviewable HTMX-driven flow in the Django admin. When adding a new restaurant or editing an existing one, the user clicks a **Fetch attributes** button; proposed values from external sources (today: Google Places) appear in a side panel showing **current vs proposed** per field, each with an Apply button that fills the corresponding form field. The user reviews and edits before saving with the standard admin Save button.

The work also generalizes the single-source `places.py` into a small "sources" abstraction (`fetch_all`) so a Michelin source can plug in later without rework. The Michelin source itself is **out of scope** for this plan — only the abstraction shape.

Existing bulk admin actions (`fetch_places_data`, `force_fetch_places_data`) stay; they are routed through the new abstraction so behavior is unchanged. A "review-style" bulk action is a follow-up plan.

## Context (from discovery)
- Files involved:
  - `restaurants/admin.py` — `RestaurantAdmin`, `save_model` (lines 50-59), bulk actions
  - `restaurants/places.py` — `search_place`, `apply_place_data`
  - `restaurants/templates/admin/restaurants/restaurant/change_form.html` — already overrides admin change form (photo dropzone). New blocks must coexist.
  - `restaurants/management/commands/fetch_places_data.py` — calls `search_place` + `apply_place_data`
  - `restaurants/tests.py` — currently empty (placeholder); this work establishes the first real tests
- Patterns found:
  - HTMX is loaded as a static asset (`restaurants/htmx.min.js`, see `templates/restaurants/base.html`). Admin pages do **not** currently load it — we must include it in our admin template override.
  - Existing change_form override uses `extrastyle` + `admin_change_form_document_ready` blocks; we'll add a separate block (likely `object-tools` for the button + extra HTML for the panel).
  - `apply_place_data` already does field-level merge with a `force=False/True` mode — the new flow makes that explicit and per-field instead of hidden.
- Dependencies:
  - `requests` (already used by `places.py`)
  - No new Python deps expected.

## Development Approach
- **Testing approach**: Regular (code first, then tests in the same task). Project's `tests.py` is empty, so this work establishes the first real tests. Focus tests on the sources function and the HTMX endpoint view. Skip template-rendering tests beyond a smoke check.
- Complete each task fully before moving to the next.
- Make small, focused changes.
- **Every task includes new/updated tests** for code changes in that task.
- All tests must pass before starting the next task.
- Run tests after each change with `uv run manage.py test restaurants`.
- Maintain backward compatibility: existing bulk admin actions and the `fetch_places_data` management command continue to work unchanged in observable behavior.

## Testing Strategy
- **Unit tests** (`restaurants/tests.py`):
  - `sources.fetch_all` — returns expected dict shape; merges multiple sources; handles `None` source response.
  - `places.search_place` adapter — already covered indirectly; light test that it conforms to the `Source` shape.
  - HTMX endpoint view — returns 302/403 when unauthenticated; returns rendered partial HTML for valid POST; handles "no results" cleanly; CSRF-protected.
- **No e2e tests**: project has none. Manual click-through is captured under Post-Completion.
- **No template snapshot tests** beyond a smoke test that admin add/change pages render 200 with the new button present.

## Progress Tracking
- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document issues/blockers with ⚠️ prefix.
- Update plan if implementation deviates from original scope.

## What Goes Where
- **Implementation Steps** (`[ ]` checkboxes): code, tests, doc updates within this repo.
- **Post-Completion** (no checkboxes): manual click-through in the admin, verification that the photo dropzone still works, README review.

## Implementation Steps

### Task 1: Extract sources abstraction
- [x] create `restaurants/sources.py` with:
  - a small `Probe` dataclass (fields: `name`, `city_name`, `location`, `latitude`, `longitude`) — enough to query a source from either a saved `Restaurant` or unsaved form data.
  - a `Source` Protocol: `__call__(probe: Probe) -> dict[str, Any] | None`.
  - a module-level `SOURCES: list[Source]` registry (initially `[google_places_source]`).
  - `fetch_all(probe: Probe) -> dict[str, FetchedValue]` where `FetchedValue` carries `value` and `source_name`. Field-level merge: first source to provide a non-empty value wins (deterministic by `SOURCES` order). Skip `None`/empty values.
- [x] in `restaurants/places.py`, add a thin `google_places_source(probe) -> dict | None` that calls `search_place(probe.name, probe.city_name, settings.GOOGLE_PLACES_API_KEY, probe.location)`. Keep `search_place` and `apply_place_data` for the existing callers.
- [x] update `RestaurantAdmin.fetch_places_data` / `force_fetch_places_data` actions and the `fetch_places_data` management command to call `fetch_all` (build a `Probe` from the restaurant) instead of `search_place` directly. Behavior must be unchanged: blank-field merge by default, full overwrite under `--force` / "Re-fetch".
- [x] write tests for `fetch_all`: returns merged dict for a single source; first-non-empty merge across two stub sources; gracefully handles a source returning `None`.
- [x] write tests confirming the bulk action / management command still produce the same `update_fields` set as before for representative inputs (use a stubbed `google_places_source`).
- [x] run `uv run manage.py test restaurants` — must pass before Task 2.

### Task 2: Add the HTMX fetch endpoint
- [x] in `RestaurantAdmin.get_urls()`, register `path("fetch-attributes/", self.admin_site.admin_view(self.fetch_attributes_view), name="restaurants_restaurant_fetch_attributes")`.
- [x] implement `fetch_attributes_view(request)`:
  - require POST; require `request.user.is_staff`.
  - read `name`, `city` (PK), `location` from POST. Build a `Probe`.
  - call `sources.fetch_all(probe)`.
  - read POSTed current values for each fetchable field (`address`, `website`, `google_maps_url`, `google_place_id`, `google_rating`, `latitude`, `longitude`).
  - render a partial (`templates/admin/restaurants/restaurant/_fetch_results.html`) with rows: field label · current value · proposed value · source · Apply button. Hide rows where current==proposed. Show a friendly message if no proposals.
- [x] in the partial, each Apply button uses HTMX OOB swap to replace the corresponding admin form input (`id_address`, `id_website`, …) with a new input pre-set to the proposed value. Also include an "Apply all" button at the top that swaps every changed field at once. (Implemented with a small inline JS click handler that copies `data-value` onto the existing form input — same observable behaviour, no extra round-trip.)
- [x] write tests for the view: 302/403 for anonymous user; 405 for GET; 200 with rows for a valid POST against a stubbed `fetch_all`; renders "no proposals" branch when `fetch_all` returns empty; CSRF protection holds (Django test client default).
- [x] run `uv run manage.py test restaurants` — must pass before Task 3.

### Task 3: Wire the button into the admin change form
- [ ] extend the existing `templates/admin/restaurants/restaurant/change_form.html` (do not rewrite — keep the photo dropzone intact):
  - add an `extrahead` block (or extend `extrastyle`) that includes `<script src="{% static 'restaurants/htmx.min.js' %}" defer></script>`. The admin doesn't load HTMX by default.
  - add an `object-tools-items` block contribution: a button that does `hx-post="{% url 'admin:restaurants_restaurant_fetch_attributes' %}"`, `hx-include="closest form"`, `hx-target="#fetch-results"`, `hx-swap="innerHTML"`. Include `{% csrf_token %}` via `hx-headers` or rely on the form's CSRF input (HTMX picks it up via `hx-include`).
  - add an empty `<div id="fetch-results"></div>` panel above the fieldsets (use a block override that injects HTML before `{{ block.super }}` for the form body, or place it in `content` block carefully).
- [ ] verify on `add/` and `<id>/change/`:
  - button appears.
  - clicking it with an empty form shows a graceful empty-state message.
  - clicking it after typing a name + selecting a city populates the panel.
  - Apply button updates the corresponding form field; form Save persists the value.
  - photo dropzone still works (regression check).
- [ ] add a smoke test: GET `/admin/restaurants/restaurant/add/` with a logged-in staff user returns 200 and contains the Fetch button text.
- [ ] run `uv run manage.py test restaurants` — must pass before Task 4.

### Task 4: Drop the silent save_model auto-fetch
- [ ] remove the `save_model` override in `restaurants/admin.py:50-59`. Keep `super().save_model()` behavior (the default).
- [ ] verify by adding a new restaurant **without** clicking Fetch: address and website remain blank (previously they'd auto-fill silently).
- [ ] update or remove any test from Task 1 that relied on the silent behavior (there shouldn't be any — this is purely a removal).
- [ ] run `uv run manage.py test restaurants` — must pass before Task 5.

### Task 5: Verify acceptance criteria
- [ ] verify all behaviors from Overview: Fetch button on add + change; per-field Apply; Apply-all; no silent auto-fetch on save; bulk admin actions unchanged.
- [ ] verify the management command `uv run manage.py fetch_places_data --city dublin` still produces equivalent output to before (sample one or two restaurants and compare).
- [ ] run full test suite: `uv run manage.py test` — must pass.
- [ ] manually confirm the admin page renders without console errors (HTMX loaded, no missing static asset 404s).

### Task 6: [Final] Update documentation
- [ ] update `README.md` under "Google Places integration" to describe the new Fetch button flow and that auto-fetch on save has been removed.
- [ ] note the sources abstraction briefly so the next contributor (or future-you adding Michelin) sees the extension point.

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`*

## Technical Details

### Probe dataclass
```python
@dataclass
class Probe:
    name: str
    city_name: str
    location: str = ""
    latitude: Decimal | None = None
    longitude: Decimal | None = None

    @classmethod
    def from_restaurant(cls, r: Restaurant) -> "Probe":
        return cls(name=r.name, city_name=r.city.name, location=r.location,
                   latitude=r.latitude, longitude=r.longitude)
```

### FetchedValue
```python
@dataclass
class FetchedValue:
    value: Any
    source_name: str  # e.g. "Google Places"
```

### `fetch_all` merge rule
For each fetchable field, iterate `SOURCES` in registration order; first source that returns a non-empty value for that field wins. Empty = `None` or `""`. Returns `dict[field_name, FetchedValue]`. Fields not provided by any source are absent from the result (rather than mapped to `None`).

### Endpoint contract
- **URL**: `admin:restaurants_restaurant_fetch_attributes`
- **Method**: POST
- **POST fields**: `name`, `city` (City PK), `location`, `address`, `website`, `google_maps_url`, `google_place_id`, `google_rating`, `latitude`, `longitude`. Anything missing is treated as empty.
- **Response**: HTML partial. Always 200 (errors render as messages in the partial, not HTTP errors).

### Fetchable fields list
Single source of truth in `sources.py`:
```python
FETCHABLE_FIELDS = ["address", "website", "google_maps_url",
                    "google_place_id", "google_rating",
                    "latitude", "longitude"]
```
Used by both `fetch_all` (which fields to merge) and the view (which POST values to read as "current"). `michelin_status` is **not** in this list yet — added when the Michelin source lands.

## Post-Completion
*Items requiring manual intervention or external systems — no checkboxes.*

**Manual verification:**
- Click through the admin add flow: type a name + city → click Fetch → review proposed values → Apply selectively → Save.
- Click through the admin change flow on an existing restaurant with already-populated fields: click Fetch → confirm only changed rows appear.
- Confirm the photo dropzone still functions (do not regress the existing override).
- Confirm no console errors and HTMX loads (network tab shows `htmx.min.js` 200).

**Future follow-ups (not part of this plan):**
- Bulk "Refresh attributes (review)" admin action with intermediate confirmation page.
- Michelin source: define data input (CSV upload, hand-curated model, …) and register it in `SOURCES`. Add `michelin_status` to `FETCHABLE_FIELDS`.
- Show field provenance (a small badge "from Google Places") on the read-only restaurant detail page if useful.
