# Add pin flag to restaurants

## Overview

Add a per-restaurant `pinned` boolean flag that floats pinned rows to the top of
the unified list view (both visited and wishlist). The toggle is admin-only —
no public UI affordance — but pinned status is visually indicated on the list
with a 📌 next to the restaurant name.

Motivation: surface restaurants the user is planning to visit soon, without
adding a wishlist-only filter and without overloading existing semantics
(Michelin stars, ratings). Pinned generalizes naturally: on the wishlist it
means "going soon", on the visited list it means "favorite/recommend".

## Context (from discovery)

- Model: `restaurants/models.py:76-164` — `Restaurant` with existing boolean
  flags `hidden` (line 137) and `closed` (line 138). Default ordering `name`.
- List view: `restaurants/views.py:100-219` — single unified `restaurant_list`,
  visited/wishlist split via `rating__isnull`. Sort logic at lines 137-151,
  `SORT_COLUMNS` at 22-28.
- List template: `restaurants/templates/restaurants/_restaurant_table.html` —
  row at line 18-26; existing Wishlist/Closed tag pattern on line 20 is the
  model to follow for the 📌 marker.
- Admin: `restaurants/admin.py:86-99` — `list_display` and `list_editable`
  already include `hidden`/`closed`; adding `pinned` follows the same pattern.
- Migrations: `restaurants/migrations/` — latest is `0015_city_hidden.py`,
  next will be `0016_restaurant_pinned.py`.
- Tests: `restaurants/tests/test_main.py` — class-based `TestCase`, fixtures
  in `setUp`. Existing sort-header tests are the model for the new sort test.

## Development Approach

- **Testing approach**: Regular (code first, then tests)
- Complete each task fully before moving to the next
- Make small, focused changes
- **CRITICAL: every task MUST include new/updated tests** for code changes
- **CRITICAL: all tests must pass before starting next task**
- Run `uv run manage.py test restaurants` after each task

## Testing Strategy

- Unit tests in `restaurants/tests/test_main.py` for:
  - Sort: pinned rows precede non-pinned rows regardless of selected sort column
  - Sort: tie-broken by the user's chosen sort within each pinned/non-pinned group
  - Template: 📌 icon renders for pinned rows only
- No e2e test framework in this project — manual verification covered in
  Post-Completion.

## Progress Tracking

- Mark completed items with `[x]` immediately when done
- Add newly discovered tasks with ➕ prefix
- Document issues/blockers with ⚠️ prefix

## Implementation Steps

### Task 1: Add `pinned` field, migration, and admin wiring

- [x] add `pinned = BooleanField(default=False, help_text="Pin to top of the list")` to `Restaurant` in `restaurants/models.py` near `hidden`/`closed` (line 137)
- [x] run `uv run manage.py makemigrations` — should produce `0016_restaurant_pinned.py`
- [x] add `"pinned"` to `RestaurantAdmin.list_display` and `list_editable` in `restaurants/admin.py:88-90`
- [x] add a model test confirming `pinned` defaults to `False`
- [x] run `uv run manage.py test restaurants` — must pass before task 2

### Task 2: Float pinned rows to top of the list view

- [x] in `restaurants/views.py:140` (inside `restaurant_list`), prepend `models.F("pinned").desc()` to `order_by_args` so pinned restaurants always come first regardless of the user-selected sort
- [x] add a test in `test_main.py` that creates pinned + unpinned restaurants and asserts pinned ones appear first under multiple sort columns (e.g. `name`, `-rating`)
- [x] run tests — must pass before task 3

### Task 3: Render 📌 marker on pinned rows

- [x] in `restaurants/templates/restaurants/_restaurant_table.html:20`, add `{% if r.pinned %} 📌{% endif %}` next to the restaurant name, mirroring the existing Wishlist/Closed tag pattern
- [x] add a view test asserting the 📌 character appears in the rendered HTML for a pinned restaurant and is absent for an unpinned one
- [x] run tests — must pass before task 4

### Task 4: Verify acceptance criteria

- [x] run full test suite `uv run manage.py test restaurants` — all green (92 tests pass)
- [x] verify `pinned` is editable from `/admin/restaurants/restaurant/` (skipped - not automatable; wired via `list_editable` in admin.py)
- [x] verify pinned rows float to the top on both visited and wishlist views (skipped - not automatable; covered by sort tests in test_main.py)

## Technical Details

- `pinned` is a simple `BooleanField(default=False)` — no index needed at this
  scale (personal tool, low row count).
- Sort precedence: `-pinned` is always the first key in `order_by(...)`. This
  must be a true `F()` expression (not a string) because the rest of the sort
  args are already expressions (`Lower(...)`, `Case`, `.desc()/.asc()`).
- Pin status visible on the list via 📌 inline with the name — chose the pin
  emoji to avoid overlap with Michelin stars (★) already in the app.
- No HTMX toggle, no new URL, no new view — admin-only toggle keeps the change
  minimal.

## Post-Completion

**Manual verification:**
- Confirm 📌 renders correctly in browser (emoji font, alignment) on a pinned
  row
- Confirm sort headers still work as expected and pinned rows stay on top when
  switching sort columns
- Confirm wishlist visibility checkbox still works — pinned wishlist entries
  should appear on top only when wishlist is shown
