# Auto-fetch Michelin status from CSV

## Overview
Register a second attribute source that fills `Restaurant.michelin_status` from a Kaggle-sourced Michelin guide CSV (`michelin_my_maps.csv`, ~19k rows). The source plugs into the existing `restaurants.sources` registry built in the previous plan, so the admin "Fetch attributes" button automatically gains a Michelin row alongside Google Places.

Name matching is fuzzy (accents, capitalization, missing words like "Bloom" vs "Bloom Brasserie") via `rapidfuzz` heuristics, with lat/lon proximity as a tiebreaker. No LLM — start simple, add one later only if accuracy is poor.

CSV updates are infrequent and semi-manual (the user re-downloads from Kaggle). Michelin handling is decoupled from live external fetches: the live `fetch_all_data` and `fetch_google_places_data` commands do **not** touch `michelin_status`, and a dedicated `update_michelin_data` command runs Michelin only with diff/review semantics for status changes (including demotions).

## Context (from discovery)
- Files to add/change:
  - `restaurants/michelin.py` (new) — CSV loader, fuzzy matcher, `michelin_source` adapter
  - `restaurants/sources.py` — register `michelin_source`; add `michelin_status` to `FETCHABLE_FIELDS`
  - `restaurants/management/commands/fetch_google_places_data.py` (renamed from `fetch_places_data.py`) — Google Places only
  - `restaurants/management/commands/fetch_all_data.py` (new) — runs all live sources (Michelin excluded)
  - `restaurants/management/commands/update_michelin_data.py` (new) — Michelin only, diff/apply
  - `restaurants/admin.py` — split bulk actions; rename Places action; add Michelin action
  - `config/settings.py` — read `MICHELIN_CSV_PATH` from env (default `BASE_DIR / "data" / "michelin_my_maps.csv"`)
  - `ansible/playbook.yml` — task to upload the local CSV to the host (idempotent via checksum)
  - `ansible/group_vars/all.yml` — `michelin_csv_path` host path
  - `ansible/templates/restaurants.service.j2` — bind-mount the CSV into the container; set `MICHELIN_CSV_PATH` env
  - `pyproject.toml` — add `rapidfuzz` dep
  - `.gitignore` — add `data/michelin_my_maps.csv`
  - `README.md` — refresh-CSV instructions; new commands; deploy flow
  - `restaurants/tests.py` — extend with matcher and source tests
- Patterns reused from `places.py` / `sources.py`:
  - Source signature: `def source(probe: Probe) -> dict | None`, with `.source_name` attribute.
  - `fetch_all(probe, sources=...)` already accepts an explicit source list — used by the new commands to scope.
  - `apply_fetched` already handles the blank-field-only vs. force merge.
- CSV format (header from sample):
  - `Name, Address, Location, Price, Cuisine, Longitude, Latitude, PhoneNumber, Url, WebsiteUrl, Award, GreenStar, FacilitiesAndServices, Description`
  - `Location` column has values like `"Dublin City, Ireland"`, `"Madrid, Spain"`. First comma-separated piece is the city.
  - `Award` values: `"3 Stars"`, `"2 Stars"`, `"1 Star"`, `"Bib Gourmand"`, `"Selected Restaurants"` → maps to `MichelinStatus` enum.
- Subtleties:
  - `michelin_status` defaults to `"none"`, not empty string. The admin per-field flow already compares current vs proposed and shows the row if they differ — no special case needed there. Bulk merge (`apply_fetched(force=False)`) will skip status updates because `"none"` is not empty; this is fine because Michelin is intentionally only run in the dedicated `update_michelin_data` command, which always writes (with explicit user opt-in via `--apply`).
  - Demotion: a restaurant previously matched in CSV may drop. The matcher returns no match → source returns `None` → `apply_fetched` leaves the field untouched. The diff command surfaces these as "no current match in CSV" entries so the user can manually demote.
  - The CSV is gitignored; the path is configurable via `MICHELIN_CSV_PATH` env var so dev and prod can place it differently.
  - Deploy flow: the local `data/michelin_my_maps.csv` is uploaded to the host via Ansible's `copy` module (which checksums and skips when unchanged). The container bind-mounts it read-only. After deploy, the user SSHes and runs `docker exec restaurants uv run manage.py update_michelin_data` against the prod DB to review the diff, then `--apply`. There is no DB sync from local → prod, so Michelin updates must be applied on the prod host (mirroring how Google Places fetches already work).

## Development Approach
- **Testing approach**: Regular (code first, then tests in the same task). Matches the prior plan's style.
- Complete each task fully before moving to the next.
- **Every task includes new/updated tests.**
- All tests must pass before the next task. Run with `uv run manage.py test restaurants`.
- Maintain backward compatibility for the renamed command: keep an alias OR document the rename in README and update any deploy/cron references. (Decision: rename cleanly, no alias — the only known caller is the README itself.)

## Testing Strategy
- **Unit tests** for matching (`restaurants/tests.py`):
  - exact match
  - case-insensitive match
  - accent-stripped match (`Forêt` vs `Foret`)
  - token-subset match (`Bloom` vs `Bloom Brasserie`)
  - geo tiebreaker resolves two close-name candidates
  - geo mismatch rejects an otherwise-good name match
  - ambiguous-name + no geo returns `None`
  - city scoping: probe in city A doesn't match a same-named restaurant in city B
  - award → `MichelinStatus` mapping covers every enum value (and unknown award returns `None`)
- **Source-shape tests**: `michelin_source(probe)` returns `{"michelin_status": ...}` or `None`; integrates with `fetch_all` (single-source and multi-source merge).
- **Command tests**:
  - `fetch_all_data` excludes `michelin_status` from updates (assert `update_fields` never contains it even when CSV has a match).
  - `fetch_google_places_data` matches old behavior of `fetch_places_data` (existing tests stay green after rename).
  - `update_michelin_data --dry-run` prints diff but writes nothing; `--apply` writes only `michelin_status`.
- **No e2e tests**: project has none. Manual click-through deferred to Post-Completion.

## Progress Tracking
- Mark completed items with `[x]` immediately when done.
- Add newly discovered tasks with ➕ prefix.
- Document blockers with ⚠️ prefix.
- Update plan if implementation deviates from original scope.

## What Goes Where
- **Implementation Steps** (`[ ]`): code, tests, doc changes within this repo.
- **Post-Completion** (no checkboxes): manual click-through, prod deploy verification, Kaggle download.

## Implementation Steps

### Task 1: Project plumbing — dependency, CSV move, setting
- [x] `uv add rapidfuzz` to add the fuzzy-matching library; verify import works.
- [x] create `data/` directory; move `michelin_my_maps.csv` from repo root to `data/michelin_my_maps.csv`.
- [x] add `data/michelin_my_maps.csv` to `.gitignore` (or `data/*.csv` if preferred).
- [x] add `MICHELIN_CSV_PATH` setting in `config/settings.py`, default `BASE_DIR / "data" / "michelin_my_maps.csv"`.
- [x] write a smoke test that `settings.MICHELIN_CSV_PATH` is set (no actual file load yet).
- [x] run `uv run manage.py test restaurants` — must pass before Task 2.

### Task 2: CSV loader and fuzzy matcher (`restaurants/michelin.py`)
- [x] create `restaurants/michelin.py` with:
  - `_normalize(s: str) -> str`: NFKD-decompose, drop combining marks, lowercase, collapse whitespace, strip non-alphanumerics-except-spaces.
  - `_AWARD_TO_STATUS: dict[str, str]` mapping CSV award strings to `Restaurant.MichelinStatus` values (`"3 Stars"` → `THREE_STARS`, etc.). Unknown awards → not in dict (matcher skips).
  - `MichelinEntry` dataclass with: `name`, `normalized_name`, `name_tokens` (set), `city_normalized`, `latitude`, `longitude`, `status`.
  - `_load_city(path: Path, city_normalized: str) -> list[MichelinEntry]`: streams the CSV row-by-row, keeps only rows whose normalized city contains `city_normalized` as a substring (handles "dublin" ⊂ "dublin city"). Module-level cache `dict[(path_str, mtime, city_normalized), list[MichelinEntry]]` so each city is scanned at most once per process; mtime keying invalidates on CSV update without restart. The full 19k-row CSV is never materialized; we only retain the ~50–200 entries for cities we actually use.
  - `match(probe: Probe) -> MichelinEntry | None`:
    - Look up candidates via `_load_city(settings.MICHELIN_CSV_PATH, _normalize(probe.city_name))`.
    - Score each candidate with `rapidfuzz.fuzz.token_set_ratio(probe.normalized_name, entry.normalized_name)`.
    - If both probe and entry have lat/lon: compute haversine distance; add a +5 bonus when ≤ 200 m, subtract 20 when > 5 km (cheap geo gating).
    - Accept best match if final score ≥ `MICHELIN_NAME_THRESHOLD` (88) AND gap to second-best ≥ `MICHELIN_AMBIGUITY_GAP` (5). Otherwise return `None`.
- [x] write tests covering every bullet from Testing Strategy → Unit tests for matching. Use a small fixture CSV (5–10 rows) under `restaurants/tests/fixtures/michelin_test.csv` to exercise real CSV parsing without depending on the gitignored production file. Override `MICHELIN_CSV_PATH` per-test. (Converted `restaurants/tests.py` into a `restaurants/tests/` package with `test_main.py` + new `test_michelin.py` so the fixtures dir can live next to tests without colliding with the module name.)
- [x] write tests for the per-city cache: `_load_city` called twice for the same city reads the file only once (assert via a counted file-open wrapper or `mock.patch("builtins.open")`); called for two different cities reads the file twice; touching the file (new mtime) invalidates the cache for that city.
- [x] write tests for `_award_to_status` covering every `MichelinStatus` enum value plus an unknown award.
- [x] run tests — must pass before Task 3.

### Task 3: Register `michelin_source` and extend `FETCHABLE_FIELDS`
- [x] in `restaurants/michelin.py`, add `def michelin_source(probe: Probe) -> dict | None`:
  - Calls `match(probe)`; returns `None` if no match.
  - Otherwise returns `{"michelin_status": entry.status}`. Nothing else — Michelin is not authoritative for address/website/cuisine in our system.
  - Set `michelin_source.source_name = "Michelin Guide"`. (Probe import switched to `TYPE_CHECKING` to avoid the circular import sources.py ↔ michelin.py.)
- [x] in `restaurants/sources.py`, add `"michelin_status"` to `FETCHABLE_FIELDS`; append `michelin_source` to `SOURCES` (so the admin "Fetch attributes" button calls it by default).
- [x] write tests:
  - `michelin_source` shape (returns dict with only `michelin_status`, or `None`).
  - `fetch_all(probe)` with both Google Places and Michelin sources (stub one of each) returns merged dict containing `michelin_status` from Michelin and `address`/`website` from Places.
- [x] run tests — must pass before Task 4. (Updated two BulkApplyTests assertions that compared `set(updated)` to `set(FETCHABLE_FIELDS)`; PAYLOAD never included `michelin_status`, so the assertions now compare against `set(PAYLOAD.keys())`.)

### Task 4: Rename Places command, add `fetch_all_data`
- [x] rename `restaurants/management/commands/fetch_places_data.py` → `fetch_google_places_data.py`. Keep behavior identical: it must continue to call `fetch_all(probe, sources=[google_places_source])` to scope to Google Places only (so adding Michelin to `SOURCES` doesn't accidentally pull Michelin in).
- [x] add `restaurants/management/commands/fetch_all_data.py`:
  - Same `--city / --all / --force` flags.
  - Calls `fetch_all(probe, sources=LIVE_SOURCES)` where `LIVE_SOURCES = [google_places_source]` (defined in `sources.py`). Michelin is intentionally excluded.
  - Identical missing-fields filter shape to the Places command, except it should not include `michelin_status` in the "missing data" predicate.
- [x] in `restaurants/sources.py`, expose `LIVE_SOURCES = [google_places_source]` alongside `SOURCES`. The admin button continues to default to `SOURCES` (all sources, including Michelin).
- [x] update existing tests for the Places command to use the new name; add a parity test that `fetch_all_data` never writes `michelin_status` even when the Michelin source would have matched (assert by stubbing both sources and inspecting `update_fields`). (Patched `google_places_source` in the command's namespace instead of `restaurants.sources.SOURCES` since the renamed command pins sources directly. New `FetchAllDataCommandTests` covers registry exclusion, command-level `update_fields` exclusion, and the missing-data predicate.)
- [x] run tests — must pass before Task 5.

### Task 5: `update_michelin_data` command (diff + apply)
- [x] add `restaurants/management/commands/update_michelin_data.py`:
  - Default mode (no flag): dry-run. Iterate restaurants (optionally `--city <slug>`); for each, run `fetch_all(probe, sources=[michelin_source])`; print one of:
    - `[name] no change (current: <status>)` — match returned same status.
    - `[name] WOULD CHANGE: <current> → <proposed>` — match returned different status.
    - `[name] no CSV match (current: <status>)` — useful for spotting demotions; the user manually fixes these.
  - With `--apply`: for each WOULD-CHANGE row, set `restaurant.michelin_status = proposed` and `save(update_fields=["michelin_status"])`. Print summary.
  - Print summary counts at end (`X would change`, `Y unchanged`, `Z no match`).
- [x] write tests:
  - dry-run prints diff and writes nothing (assert DB state unchanged).
  - `--apply` writes only `michelin_status` (assert `update_fields == ["michelin_status"]` via mocking `save`).
  - "no CSV match" path is correctly classified.
  - `--city` filter scopes the queryset.
- [x] run tests — must pass before Task 6.

### Task 6: Admin actions split
- [x] in `restaurants/admin.py`:
  - Rename action `fetch_places_data` description from "Fetch Google Places data" to "Fetch Google Places data" (already correct) but ensure it scopes to `[google_places_source]` (it routes through `fetch_all` which now includes Michelin by default — pin sources explicitly).
  - Rename `force_fetch_places_data` similarly: pin to `[google_places_source]`.
  - Add new actions `update_michelin_status` and `force_update_michelin_status`: same pattern but pinned to `[michelin_source]`. Force version overwrites current `michelin_status` even when current is non-empty (since `none` is the default).
- [x] write tests for the new admin actions (mirror the existing places-action tests) using the staff client. (Replaced the per-action `_do_fetch_places` helper with a shared `_run_sources` that takes an explicit `sources` list and label, then added direct-method-call tests using `RequestFactory` + `FallbackStorage`.)
- [x] run tests — must pass before Task 7.

### Task 7: Wire CSV into Ansible deploy
- [x] in `ansible/group_vars/all.yml`, add `michelin_csv_dir: /opt/restaurants/data` and `michelin_csv_path: "{{ michelin_csv_dir }}/michelin_my_maps.csv"`.
- [x] in `ansible/playbook.yml`:
  - extend the existing "Create data subdirectories" loop to also create `{{ michelin_csv_dir }}` (owner ec2-user, mode 0755).
  - add a `stat` task on the controller checking the local `data/michelin_my_maps.csv`; register the result.
  - add a `copy` task that uploads the local CSV to `{{ michelin_csv_path }}`, gated by `when: <stat>.stat.exists`. The `copy` module checksums and only transfers when content differs — a no-op deploy after a CSV update is one transfer; subsequent deploys are no-ops. Owner ec2-user, mode 0644.
  - if the local CSV is absent, log a `debug` message ("Skipping Michelin CSV upload — no local file") and continue. A fresh checkout without the CSV must not break the deploy.
  - ensure the CSV upload does NOT trigger a restaurants restart (the CSV is read at command-invocation time, not container start). No `notify:` line.
  - (also added) "Ensure Michelin CSV file exists" `touch` task before the upload, mirroring the existing db-file pattern, so Docker's bind-mount doesn't auto-create a directory at the source path on a fresh host without a local CSV.
- [x] in `ansible/templates/restaurants.service.j2`:
  - add `-v {{ michelin_csv_path }}:/app/data/michelin_my_maps.csv:ro` to the `docker run` command.
  - add `-e MICHELIN_CSV_PATH=/app/data/michelin_my_maps.csv` to the env vars.
- [x] in `config/settings.py`, change `MICHELIN_CSV_PATH` to read from env first, falling back to `BASE_DIR / "data" / "michelin_my_maps.csv"`. Update the Task 1 smoke test accordingly. (Already in this shape from Task 1; no change needed. Smoke test still asserts default path components.)
- [x] write a test that `MICHELIN_CSV_PATH` honors the env var (use `override_settings` or set/unset env in the test). (Reloads `config.settings` with `MICHELIN_CSV_PATH` set in `os.environ` and asserts the resolved path; reloads again to restore.)
- [x] run `uv run manage.py test restaurants` — must pass before Task 8.

### Task 8: Verify acceptance criteria
- [ ] verify all six behaviors from Overview:
  1. CSV-driven fuzzy matching works for accent / casing / missing-word cases (covered by Task 2 tests).
  2. `michelin_source` plugs into `fetch_all` (covered by Task 3 tests).
  3. Three management commands exist with the agreed scopes (covered by Tasks 4, 5).
  4. Admin "Fetch attributes" button now offers a Michelin row (covered by Task 3 tests + smoke test below).
  5. CSV is gitignored and path is configurable (covered by Task 1 + Task 7 tests).
  6. Deploy uploads the CSV idempotently (verified manually — see Post-Completion).
- [ ] add a smoke test: with the test fixture CSV path set, an admin GET on `/admin/restaurants/restaurant/<id>/change/` followed by a POST to the fetch-attributes endpoint produces a panel containing a `michelin_status` row when the restaurant matches the fixture.
- [ ] run full test suite: `uv run manage.py test`.
- [ ] run linter if the project has one configured (check `pyproject.toml`); fix any issues.

### Task 9: [Final] Update documentation
- [ ] update `README.md`:
  - "Google Places integration" section: rename `fetch_places_data` → `fetch_google_places_data`; add `fetch_all_data` description.
  - new "Michelin guide integration" section explaining:
    - data source: download CSV from Kaggle (link the dataset page) and place at `data/michelin_my_maps.csv`.
    - local refresh: re-download, replace the file, run `uv run manage.py update_michelin_data` to see the diff, then `--apply`.
    - production refresh: replace the local CSV, run `./deploy.sh` (Ansible uploads the CSV iff it changed; no container restart), then SSH and `docker exec restaurants uv run manage.py update_michelin_data` (`--apply` after reviewing).
    - admin actions: "Update Michelin status" / "Re-fetch Michelin status (overwrite)".
    - note that `michelin_status` is not part of `fetch_all_data` because Michelin updates are infrequent and reviewed separately.
- [ ] mention `MICHELIN_CSV_PATH` env var briefly (default location, container path, override knob).

*Note: ralphex automatically moves completed plans to `docs/plans/completed/`.*

## Technical Details

### Award → MichelinStatus mapping
```python
_AWARD_TO_STATUS = {
    "3 Stars":               Restaurant.MichelinStatus.THREE_STARS,
    "2 Stars":               Restaurant.MichelinStatus.TWO_STARS,
    "1 Star":                Restaurant.MichelinStatus.ONE_STAR,
    "Bib Gourmand":          Restaurant.MichelinStatus.BIB_GOURMAND,
    "Selected Restaurants":  Restaurant.MichelinStatus.SELECTED,
}
```

### Matcher pseudocode
```python
def match(probe):
    entries = _load_city(settings.MICHELIN_CSV_PATH, _normalize(probe.city_name))
    if not entries:
        return None
    probe_norm = _normalize(probe.name)
    scored = []
    for e in entries:
        score = rapidfuzz.fuzz.token_set_ratio(probe_norm, e.normalized_name)
        if probe.latitude and probe.longitude and e.latitude and e.longitude:
            d = haversine_m(probe, e)
            if d <= 200: score += 5
            elif d > 5000: score -= 20
        scored.append((score, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored or scored[0][0] < MICHELIN_NAME_THRESHOLD:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MICHELIN_AMBIGUITY_GAP:
        return None
    return scored[0][1]
```

### Source registry layout (after this plan)
```python
LIVE_SOURCES: list[Source] = [google_places_source]
SOURCES:      list[Source] = [google_places_source, michelin_source]  # default for fetch_all
FETCHABLE_FIELDS = [
    "address", "website", "google_maps_url", "google_place_id",
    "google_rating", "latitude", "longitude",
    "michelin_status",
]
```

- Admin "Fetch attributes" button → `fetch_all(probe)` → uses `SOURCES`.
- `fetch_all_data` command → `fetch_all(probe, sources=LIVE_SOURCES)`.
- `fetch_google_places_data` command → `fetch_all(probe, sources=[google_places_source])`.
- `update_michelin_data` command → `fetch_all(probe, sources=[michelin_source])`.

### Threshold constants
```python
MICHELIN_NAME_THRESHOLD = 88   # token_set_ratio cutoff
MICHELIN_AMBIGUITY_GAP  = 5    # min gap between top-1 and top-2
MICHELIN_GEO_BONUS_M    = 200  # ≤ this many meters → +5 score
MICHELIN_GEO_PENALTY_M  = 5000 # > this many meters → −20 score
```
Tunable; live in `restaurants/michelin.py` as module constants.

## Post-Completion
*Items requiring manual intervention or external systems — no checkboxes.*

**Manual verification:**
- Download the latest CSV from Kaggle (`michelin_my_maps`) and place at `data/michelin_my_maps.csv`.
- Run `uv run manage.py update_michelin_data --city dublin` and review the diff.
- Spot-check three known matches (e.g. Chapter One, Patrick Guilbaud, The Old Spot) — confirm the matcher resolves correctly with the production CSV.
- Spot-check that "Bloom" (or similar truncated names in the user's data) matches "Bloom Brasserie" (or whatever variant exists in CSV).
- Click through the admin add/change form: Fetch attributes panel should now show a Michelin row when the restaurant has a CSV match.
- After `--apply`, confirm the public detail page reflects the new status.

**Deploy verification:**
- First deploy after this plan lands: run `./deploy.sh`; confirm the CSV upload task reports `changed`.
- Second deploy with no CSV change: confirm the CSV task reports `ok` (idempotent — Ansible's `copy` checksum match).
- After uploading: SSH to the host, `docker exec restaurants ls -la /app/data/michelin_my_maps.csv` to confirm the bind-mount.
- Run `docker exec restaurants uv run manage.py update_michelin_data` against prod, review diff, `--apply`.
- Confirm a deploy with a missing local CSV does not fail (skip task should fire).

**Future follow-ups (not part of this plan):**
- LLM tiebreaker for the ambiguous-zone (60–88) — only if the heuristic produces too many false negatives in practice.
- Kaggle API auto-download on a cron (`update_michelin_data --download-from-kaggle`) — currently overkill for personal use.
- Per-`City` alias field (instead of pure substring matching) if international city naming gets messy.
- Surface CSV match metadata (matched name, score, distance) in admin or detail page.
