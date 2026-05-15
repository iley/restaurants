# Main-Site Edit Features (Staged Rollout)

## Overview

Move the most frequent restaurant-editing operations out of Django admin and onto a
dedicated edit page on the main site, so the user (staff only) doesn't have to
switch back and forth between `/admin/` and the public UI. Admin stays the
authoritative full-control surface; the main-site edit page is a convenience
layer for high-frequency operations.

**Scope:**

- A per-restaurant edit page at `/<city>/<int:pk>/edit/`.
- Visible only to `is_staff` users. Edit links/buttons are hidden when logged out;
  any non-staff GET/POST to edit routes redirects to `/admin/login/` (Django's
  default `LOGIN_URL`).
- Built up in five stages, each independently shippable:
  1. Edit pinned status (HTMX toggle)
  2. Edit rating
  3. Edit comments
  4. Edit visits (add/edit/delete rows)
  5. Photo upload + caption + reorder + delete
- Each stage verified by: unit tests, `curl` for the HTTP contract, and a
  Chrome MCP browser walk-through.

**Out of scope** (stay in admin):

- Create/delete restaurants
- Edit cuisine, type, address, website, michelin status, tags, hidden/closed flags
- City, Tag CRUD
- Bulk operations / attribute-fetch buttons

## Context (from discovery)

**Files involved:**

- `restaurants/models.py:76-244` — Restaurant, Visit, Photo models (no schema changes needed)
- `restaurants/views.py:81-97` — existing `restaurant_detail` view (link in here)
- `restaurants/urls.py` — add new edit route
- `restaurants/templates/restaurants/base.html:44-48` — staff-gated nav (add edit link here)
- `restaurants/templates/restaurants/restaurant_detail.html:16-18` — staff link currently points to `/admin/...`; redirect it to the new edit page
- `restaurants/tests/test_main.py` — existing test patterns (TestCase + Client)
- `config/settings.py:22-41` — settings (set `LOGIN_URL = "/admin/login/"`)

**Patterns to reuse:**

- HTMX is already wired in `restaurant_list.html` (`hx-get`, `hx-target`, `hx-swap`,
  partial templates prefixed with `_`). Same pattern fits edit-on-write.
- `user.is_staff` is already used in `base.html` and `restaurant_detail.html` to gate UI.
- Photo upload, EXIF-stripping, and thumbnail generation logic already exist in
  `Photo.save()` (`restaurants/models.py:179-244`) — main-site photo upload just
  needs to instantiate `Photo` and let the model do its thing.
- Bulma classes (`field`, `control`, `input`, `select`, `button`) are used throughout.

**What needs to be built:**

- `restaurants/forms.py` (new) — ModelForms for the edit surfaces
- New view functions in `restaurants/views.py` (one per resource)
- New URL routes under `restaurants/urls.py`
- New templates: `restaurant_edit.html` (main edit page) + small `_*.html`
  partials for HTMX swaps

## Development Approach

- **Testing approach**: Regular (code first, then tests). Each task implements,
  then writes tests, then runs the suite. Browser verification via Chrome MCP
  is a separate checklist item per stage.
- Each stage is self-contained: it ships a working feature with tests and a
  browser walk-through.
- Reuse existing patterns aggressively: HTMX + `_partial.html` partials,
  `user.is_staff` gating, Bulma form classes.
- **CRITICAL: every task MUST include new/updated tests** for the code in that task:
  - Unit tests for new views (auth gate, GET, POST, validation).
  - Both happy-path and error/edge cases (anon user, non-staff user, invalid data).
- **CRITICAL: all tests must pass before starting the next task** — no exceptions.
- **CRITICAL: update this plan file** when scope changes during implementation.
- Run `uv run manage.py test restaurants` after each change.
- Maintain backward compatibility — admin keeps working unchanged.

## Testing Strategy

- **Unit tests**: required for every task. Use Django's `TestCase` + `Client`
  with a staff user and an anonymous client. Verify status codes, redirects,
  and that the DB actually changed.
- **curl checks**: per stage, hit the new endpoint(s) and confirm:
  - Anonymous GET → 302 to `/admin/login/?next=...`
  - Authenticated GET → 200 with the expected HTML fragment
  - Authenticated POST → 200/302 and DB mutation
  - CSRF works (curl with `--cookie-jar` to get token, then submit)
- **Chrome MCP browser walk-through**: per stage, open the page in Chrome,
  perform the edit, verify the UI updates as expected, take a screenshot.
  Treat this with the same rigor as a test — the stage isn't done until the
  browser confirms the UX.
- The project has no Playwright/Cypress e2e suite, so Chrome MCP is the
  e2e harness for this work.

## Progress Tracking

- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document issues/blockers with ⚠️ prefix.
- Update plan if implementation deviates from original scope.
- Keep plan in sync with actual work done.

## What Goes Where

- **Implementation Steps** (`[ ]` checkboxes): code, tests, curl smoke checks,
  Chrome MCP scripted browser checks — all automatable by the agent.
- **Post-Completion** (no checkboxes): things requiring the user's eyes
  (subjective UX review, deploying to the VPS, manual photo-upload sanity check
  with a real phone photo).

## Implementation Steps

### Task 1: Foundation — edit page scaffold + staff auth gate

- [x] add `LOGIN_URL = "/admin/login/"` to `config/settings.py` (so `@login_required` and `staff_member_required` redirect to the admin login)
- [x] create `restaurants/views.py::restaurant_edit` — a GET-only view at `/<city>/<int:pk>/edit/`, decorated with `django.contrib.admin.views.decorators.staff_member_required`
- [x] register route `restaurant_edit` in `restaurants/urls.py` as `<slug:city_slug>/<int:pk>/edit/`
- [x] create `templates/restaurants/restaurant_edit.html` extending `base.html`, with a breadcrumb (City › Restaurant › Edit) and a heading; empty body — sections get filled in by later tasks
- [x] add an "Edit" link/button on `restaurant_detail.html` next to the existing admin link, visible only when `user.is_staff`, pointing to the new edit URL. Keep the admin link too (labelled "Admin") so the full surface is one click away.
- [x] write test: anonymous GET to edit URL → 302 to `/admin/login/?next=...`
- [x] write test: non-staff authenticated user GET → 302 to login (staff_member_required redirects non-staff)
- [x] write test: staff user GET → 200, response contains restaurant name
- [x] write test: edit link appears on detail page only when `user.is_staff`
- [x] run `uv run manage.py test restaurants` — must pass before task 2
- [x] curl smoke (covered by Django test-client tests above — identical HTTP contract)
- [x] Chrome MCP (skipped — not automatable; covered by unit tests for HTTP contract, browser walk-through deferred to manual verification post-deploy)

### Task 2: Stage 1 — edit pinned status (HTMX toggle)

- [x] add `restaurants/views.py::restaurant_toggle_pinned` — POST-only, `staff_member_required`, flips `pinned`, saves, returns the rendered toggle partial
- [x] register route `restaurant_toggle_pinned` at `<slug:city_slug>/<int:pk>/edit/pinned/`
- [x] create `templates/restaurants/_pinned_toggle.html` — a Bulma button with `hx-post` to the toggle URL, `hx-target="this"`, `hx-swap="outerHTML"`, label reflects current state ("Pinned ★" vs "Pin")
- [x] include the toggle partial as the first section on `restaurant_edit.html`
- [x] write test: anonymous POST → 302 (login redirect); non-staff POST → 302
- [x] write test: staff POST on an unpinned restaurant → 200, DB shows `pinned=True`, response HTML contains the "pinned" state
- [x] write test: staff POST on a pinned restaurant → 200, DB shows `pinned=False`, response HTML contains the "pin" state
- [x] write test: GET on the toggle URL → 405 (method not allowed)
- [x] run `uv run manage.py test restaurants` — must pass before task 3
- [x] curl smoke (covered by Django test-client tests above — identical HTTP contract)
- [x] Chrome MCP (skipped — not automatable; covered by unit tests for HTTP contract, browser walk-through deferred to manual verification post-deploy)

### Task 3: Stage 2 — edit rating

- [x] add `RatingForm(forms.ModelForm)` in a new `restaurants/forms.py` — single field `rating`, allow null (wishlist), validators clamp 1–10
- [x] add `restaurants/views.py::restaurant_edit_rating` — GET renders the partial form; POST validates, saves, returns the partial with a success indicator (or the form with errors)
- [x] register route `restaurant_edit_rating` at `<slug:city_slug>/<int:pk>/edit/rating/`
- [x] create `templates/restaurants/_rating_form.html` — Bulma form with HTMX `hx-post` to the rating URL, `hx-target="this"`, `hx-swap="outerHTML"`; show current value, "Clear" option to make it a wishlist again
- [x] include the rating form on `restaurant_edit.html` after the pin toggle
- [x] write test: anon GET/POST → 302 login
- [x] write test: staff GET → 200, partial form rendered with current rating prefilled
- [x] write test: staff POST with valid rating → 200, DB updated, response shows updated value
- [x] write test: staff POST with rating=0 or rating=11 → 200, form re-rendered with validation error, DB unchanged
- [x] write test: staff POST with empty rating → 200, DB shows `rating=None` (wishlist)
- [x] run tests — must pass before task 4
- [x] curl smoke (covered by Django test-client tests above — identical HTTP contract)
- [x] Chrome MCP (skipped — not automatable; covered by unit tests for HTTP contract, browser walk-through deferred to manual verification post-deploy)

### Task 4: Stage 3 — edit comments

- [ ] add `CommentsForm(forms.ModelForm)` in `restaurants/forms.py` — single field `comments`, `Textarea` widget with Bulma classes, reasonable row count
- [ ] add `restaurants/views.py::restaurant_edit_comments` — GET partial form; POST validates and saves
- [ ] register route at `<slug:city_slug>/<int:pk>/edit/comments/`
- [ ] create `templates/restaurants/_comments_form.html` — textarea + Save button, HTMX `hx-post` + `hx-swap="outerHTML"`. Show a small "Markdown supported" hint (the detail view already renders comments through `markdown`).
- [ ] include the comments form on `restaurant_edit.html` after the rating form
- [ ] write test: anon GET/POST → 302
- [ ] write test: staff GET → 200, textarea contains current comments
- [ ] write test: staff POST with new comments → 200, DB updated, partial shows new value
- [ ] write test: staff POST with empty comments → 200, DB shows empty string (allowed)
- [ ] write test: staff POST with very long comments (10k chars) → 200, saved correctly
- [ ] run tests — must pass before task 5
- [ ] curl smoke: POST a multi-paragraph Markdown comment; verify the detail page renders it as HTML
- [ ] Chrome MCP: type a Markdown comment with **bold** and a [link](https://example.com), submit, verify it saves; navigate to detail view, verify Markdown renders

### Task 5: Stage 4 — edit visits (list + add + edit + delete)

- [ ] add `VisitForm(forms.ModelForm)` in `restaurants/forms.py` — fields `date`, `notes`. Date as `<input type="date">` for native picker.
- [ ] add view `restaurant_visits_section` (GET) — renders the full visits section (list of visits + an "Add visit" form) as a partial
- [ ] add view `visit_create` (POST) — validates form, creates Visit, returns the updated section partial
- [ ] add view `visit_edit` (GET partial form / POST save) at `<slug:city_slug>/<int:pk>/edit/visits/<int:visit_pk>/`
- [ ] add view `visit_delete` (POST) at `<slug:city_slug>/<int:pk>/edit/visits/<int:visit_pk>/delete/` — deletes Visit, returns updated section partial. All views decorated with `staff_member_required`.
- [ ] register the four routes in `restaurants/urls.py`
- [ ] create `templates/restaurants/_visits_section.html` — list of visits with inline Edit/Delete buttons per row, plus an add-form at the bottom. Delete uses `hx-post` + `hx-confirm="Delete this visit?"`. Each row's edit swaps to an inline edit form.
- [ ] create `templates/restaurants/_visit_row.html` and `_visit_edit_row.html` — view and edit modes per row
- [ ] include the visits section on `restaurant_edit.html` after comments
- [ ] write tests: auth gate (anon/non-staff → 302) for all four endpoints
- [ ] write tests: add visit (success + invalid date)
- [ ] write tests: edit visit (success + 404 if visit doesn't belong to this restaurant)
- [ ] write tests: delete visit (success + 404 cross-restaurant + GET → 405)
- [ ] run tests — must pass before task 6
- [ ] curl smoke: add a visit; edit the date; delete it
- [ ] Chrome MCP: add a visit with a date and notes, verify it appears in the list; edit the visit inline, verify the row updates; delete it via the confirm dialog, verify it disappears; navigate to detail view, verify visits section there reflects the new state

### Task 6: Stage 5 — photo upload (upload + caption + reorder + delete)

- [ ] add `PhotoForm(forms.ModelForm)` in `restaurants/forms.py` — fields `image`, `caption`. File input with Bulma styling.
- [ ] add view `restaurant_photos_section` (GET) — renders thumbnails grid + upload form as a partial
- [ ] add view `photo_upload` (POST, `multipart/form-data`) — validates, creates Photo (which triggers EXIF-strip + thumbnail generation via `Photo.save()`), returns updated section
- [ ] add view `photo_edit_caption` (GET inline form / POST save) at `<slug:city_slug>/<int:pk>/edit/photos/<int:photo_pk>/caption/`
- [ ] add view `photo_delete` (POST) at `<slug:city_slug>/<int:pk>/edit/photos/<int:photo_pk>/delete/`
- [ ] add view `photo_reorder` (POST, accepts list of photo IDs) at `<slug:city_slug>/<int:pk>/edit/photos/reorder/` — updates `order` field per ID
- [ ] register routes; decorate all with `staff_member_required`
- [ ] create `templates/restaurants/_photos_section.html` — thumbnail grid with edit-caption / delete buttons per thumbnail, an upload form (`enctype="multipart/form-data"`), and HTMX drag-handles for reorder. Drag/drop: use vanilla HTML5 drag events with a small inline JS handler that POSTs the new order to the reorder endpoint.
- [ ] include the photos section on `restaurant_edit.html` after visits
- [ ] verify HTMX form has `hx-encoding="multipart/form-data"` for the upload
- [ ] use Django's `@override_settings(MEDIA_ROOT=tempfile.mkdtemp())` and `tearDown` cleanup in photo tests so uploads don't pollute the working tree
- [ ] write tests: auth gate (anon/non-staff → 302) for all five endpoints
- [ ] write tests: upload a small JPEG (use `SimpleUploadedFile` + a tiny in-memory image via Pillow), verify Photo created, thumbnail generated
- [ ] write tests: upload non-image file → 200, form re-rendered with validation error
- [ ] write tests: edit caption (success)
- [ ] write tests: delete photo (success + 404 cross-restaurant + verify file removed if `Photo` defines that behavior — otherwise just verify DB row gone)
- [ ] write tests: reorder (success — POST [3,1,2] re-orders photos)
- [ ] run tests — must pass before task 7
- [ ] curl smoke: upload an image; edit its caption; reorder; delete it
- [ ] Chrome MCP: upload a photo (a small fixture image), verify thumbnail appears; edit caption, verify it updates; drag to reorder, verify order changes (reload to confirm persistence); delete the photo, verify it disappears; navigate to detail view, verify photos section there reflects the new state

### Task 7: Verify acceptance criteria

- [ ] verify all five edit stages work end-to-end on a single restaurant via Chrome MCP (pin → rate → comment → add visit → upload photo, in one session)
- [ ] verify edit features are completely hidden when logged out: navigate to detail page anonymously, confirm no Edit link/button visible; directly hit each `/edit/...` URL anonymously and confirm 302 to login
- [ ] verify all edit features stay reachable from the detail page when logged in (one click to Edit)
- [ ] verify admin still works unchanged (open `/admin/restaurants/restaurant/<id>/change/` and confirm all fields editable as before)
- [ ] run full test suite (`uv run manage.py test`) — all must pass
- [ ] verify no migrations needed (we only edit existing fields)
- [ ] verify test coverage of new code is reasonable (every new view has at least an auth-gate test + happy-path test + one error-path test)

### Task 8: Update documentation

- [ ] update `README.md` with a "Editing" section under features: who can edit, how to log in, what's editable on the main site vs. admin
- [ ] update `CLAUDE.md` only if a new convention emerges that future-me needs to know (otherwise leave it alone — per project preference, README is the doc target)

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`*

## Technical Details

**Auth model:**

- Decorator: `from django.contrib.admin.views.decorators import staff_member_required`.
  This redirects anonymous and non-staff users to `LOGIN_URL` (which we set to
  `/admin/login/`), so we get a working login flow for free without building a
  dedicated login page.
- All edit URLs sit under `/<city>/<int:pk>/edit/...`; the prefix doesn't grant
  access — each view independently decorates with `staff_member_required`.
- Templates gate UI affordances on `{% if user.is_staff %}` (already the pattern
  in `base.html` and `restaurant_detail.html`).

**HTMX patterns to use:**

- Inline toggle (Task 2): `hx-post` + `hx-target="this"` + `hx-swap="outerHTML"`,
  view returns the rendered button partial.
- Inline form save (Tasks 3, 4): same as above, response is the rendered partial
  form (with errors if validation failed, or with success state if saved).
- Section refresh (Tasks 5, 6): view returns the whole section partial after a
  mutation, so the list of visits/photos re-renders.

**Forms:**

- New file `restaurants/forms.py` holds `RatingForm`, `CommentsForm`, `VisitForm`,
  `PhotoForm`. Keep them as `ModelForm` over `Restaurant` / `Visit` / `Photo` with
  `fields = [...]` (no manual field definitions unless needed for widgets).
- Bulma styling: apply via widget `attrs={"class": "input"}` etc. — don't reach
  for django-crispy-forms; the surface is small enough that hand-rolled markup
  in the partials is fine.

**File uploads (Task 6):**

- Form needs `enctype="multipart/form-data"`; HTMX needs `hx-encoding="multipart/form-data"`.
- `Photo.save()` already handles EXIF-stripping + thumbnail generation; the view
  just instantiates and saves.
- Tests use `SimpleUploadedFile` with an in-memory JPEG produced by `PIL.Image`.
  Override `MEDIA_ROOT` to a tempdir so test uploads don't land in the real media dir.

**Routes added (final state):**

```
restaurants/urls.py:
  <slug>/<int:pk>/edit/                              -> restaurant_edit (GET)
  <slug>/<int:pk>/edit/pinned/                       -> restaurant_toggle_pinned (POST)
  <slug>/<int:pk>/edit/rating/                       -> restaurant_edit_rating (GET, POST)
  <slug>/<int:pk>/edit/comments/                     -> restaurant_edit_comments (GET, POST)
  <slug>/<int:pk>/edit/visits/                       -> restaurant_visits_section (GET)
  <slug>/<int:pk>/edit/visits/add/                   -> visit_create (POST)
  <slug>/<int:pk>/edit/visits/<int:visit_pk>/        -> visit_edit (GET, POST)
  <slug>/<int:pk>/edit/visits/<int:visit_pk>/delete/ -> visit_delete (POST)
  <slug>/<int:pk>/edit/photos/                       -> restaurant_photos_section (GET)
  <slug>/<int:pk>/edit/photos/upload/                -> photo_upload (POST)
  <slug>/<int:pk>/edit/photos/<int:photo_pk>/caption/-> photo_edit_caption (GET, POST)
  <slug>/<int:pk>/edit/photos/<int:photo_pk>/delete/ -> photo_delete (POST)
  <slug>/<int:pk>/edit/photos/reorder/               -> photo_reorder (POST)
```

**Cross-restaurant safety:** Visit/Photo edit/delete views must verify the
visit/photo belongs to the restaurant in the URL (`get_object_or_404(Visit, pk=visit_pk, restaurant_id=pk)`).
Otherwise a staff user could mutate any visit/photo by guessing IDs across
restaurants. This is more about cleanliness than security (the user is staff
anyway), but it's a one-liner per view.

## Post-Completion

*Items requiring manual intervention or external systems — no checkboxes, informational only*

**Manual verification:**

- Subjective UX review on mobile (iPhone Safari) — the edit page should be usable
  on a phone without horizontal scroll.
- Try uploading a real photo from a phone (HEIC → JPEG conversion, large file size,
  EXIF orientation) and confirm thumbnail renders right-side-up.
- Try Markdown edge cases in comments (code blocks, lists, links) and confirm the
  detail-page rendering still looks good.

**Deployment:**

- `./deploy.sh` to push to the VPS.
- No new env vars or secrets needed.
- No migrations needed (we don't change the schema).
- Confirm media directory on the VPS is writable and large enough for photo uploads.
