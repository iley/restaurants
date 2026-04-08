# City Maps

Add an interactive map view to each city page, showing restaurant locations on
a self-hosted map. Users can toggle between the existing list view and a map
view. All filters work in both modes.

## Goals

- Fully self-hosted: zero external requests at runtime (no CDN, no tile
  services, no external fonts).
- Per-city maps, matching the existing per-city list view.
- Minimal frontend complexity: vanilla JS, no build step.

## Stack

| Layer | Technology |
|-------|-----------|
| Tile format | [PMTiles](https://docs.protomaps.com/pmtiles/) — single-file tile archive, served as a static file via nginx. Browser fetches individual tiles using HTTP Range Requests. No tile server process needed. |
| Tile source | City extracts from the [Protomaps daily planet build](https://docs.protomaps.com/basemaps/downloads), cut with `pmtiles extract`. |
| Tile styling | [Protomaps basemap styles](https://docs.protomaps.com/basemaps/maplibre) ("light" flavor). Fonts and sprites from [basemaps-assets](https://github.com/protomaps/basemaps-assets), vendored into static files. |
| Frontend map library | [MapLibre GL JS](https://maplibre.org/maplibre-gl-js/docs/) — WebGL vector tile renderer. Vendored JS + CSS in static files. |
| PMTiles JS | [pmtiles.js](https://github.com/protomaps/PMTiles) — browser-side protocol handler for Range Request tile fetching. Vendored. |
| Basemap styles JS | [@protomaps/basemaps](https://www.npmjs.com/package/@protomaps/basemaps) — generates MapLibre style layers. Vendored. |

## Model Changes

### City: add bounding box

Four new `DecimalField`s on `City`:

```
bbox_min_lon  (max_digits=9, decimal_places=6)
bbox_min_lat  (max_digits=9, decimal_places=6)
bbox_max_lon  (max_digits=9, decimal_places=6)
bbox_max_lat  (max_digits=9, decimal_places=6)
```

All nullable/blank — a city without a bbox simply won't have a map tab.

Used for: (1) the `pmtiles extract --bbox` command, (2) setting the initial map
viewport. The City admin page will include a help link to
[bboxfinder.com](http://bboxfinder.com) for looking up values.

### Restaurant: add coordinates

Two new `DecimalField`s on `Restaurant`:

```
latitude   (max_digits=9, decimal_places=6, null, blank)
longitude  (max_digits=9, decimal_places=6, null, blank)
```

## Google Places Integration

Add `places.location` to the field mask in `places.py`. The API returns:

```json
{"location": {"latitude": 53.349805, "longitude": -6.260310}}
```

The existing `apply_place_data` fill-in-the-blanks logic handles the new fields
naturally: a normal (non-force) fetch will populate `latitude`/`longitude` only
on restaurants where they're currently null, leaving all other fields untouched.

After deploying the model change, run:

```bash
uv run manage.py fetch_places_data --all
```

This will fill in coordinates for all restaurants without touching existing
data.

## Tile Management

### Storage

PMTiles files live outside the Django static/media directories, in a dedicated
tiles directory on the VPS (e.g. `/opt/restaurants/tiles/`). Nginx serves them
directly.

Estimated size: ~50-80 MB per city at maxzoom 15.

### Fetching tiles: management command + admin action

A new management command `fetch_tiles` extracts a city's tiles from the
Protomaps daily build:

```bash
uv run manage.py fetch_tiles --city dublin
uv run manage.py fetch_tiles              # all cities with a bbox
```

Under the hood this runs:

```
pmtiles extract <protomaps-daily-url> <output>.pmtiles \
    --bbox=<min_lon>,<min_lat>,<max_lon>,<max_lat> \
    --maxzoom=15
```

The `pmtiles` CLI binary needs to be available on the server. The command
downloads ~50-80 MB per city from the Protomaps build — this takes a few
minutes.

An admin action ("Fetch map tiles") is also available on the City model. It
spawns the management command as a background subprocess and returns
immediately, so a browser disconnect won't kill it.

The operation is idempotent — re-running overwrites the existing file.

### Nginx configuration

```nginx
location /tiles/ {
    alias /opt/restaurants/tiles/;
    add_header Access-Control-Allow-Origin *;
    expires 30d;
    add_header Cache-Control "public, immutable";
}
```

### Vendored static assets

All JS libraries, CSS, fonts, and sprites are vendored into
`restaurants/static/restaurants/map/`:

```
static/restaurants/map/
    maplibre-gl.js
    maplibre-gl.css
    pmtiles.js
    basemaps.js
    fonts/                  # from protomaps/basemaps-assets
        Noto Sans Regular/
            0-255.pbf
            ...
    sprites/                # from protomaps/basemaps-assets
        v4/
            light.json
            light.png
            light@2x.json
            light@2x.png
```

## Frontend

### List/map toggle

Two Bulma tabs below the filter form: **List** and **Map**. Clicking a tab
swaps the content area via HTMX. The filter dropdowns remain above both views
and work identically in either mode.

When the map tab is active:
- The `#restaurant-table` div is replaced with a `#restaurant-map` div
  containing the MapLibre map.
- Filter changes trigger an HTMX request that returns updated restaurant data
  as JSON (or re-renders the map partial with updated marker data).

### Map rendering (vanilla JS)

```js
// Register the PMTiles protocol
const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

// Initialize map with self-hosted tiles, fonts, sprites
const map = new maplibregl.Map({
    container: "map",
    style: {
        version: 8,
        glyphs: "/static/restaurants/map/fonts/{fontstack}/{range}.pbf",
        sprite: "/static/restaurants/map/sprites/v4/light",
        sources: {
            protomaps: {
                type: "vector",
                url: "pmtiles:///tiles/<city-slug>.pmtiles",
                attribution: "&copy; OpenStreetMap"
            }
        },
        layers: basemaps.layers("protomaps", basemaps.namedFlavor("light"), {lang: "en"})
    },
    center: [<city-center-lon>, <city-center-lat>],
    zoom: 13
});

// Add markers for each restaurant
restaurants.forEach(r => {
    new maplibregl.Marker()
        .setLngLat([r.longitude, r.latitude])
        .setPopup(new maplibregl.Popup().setHTML(`<b>${r.name}</b><br>${r.cuisine}`))
        .addTo(map);
});
```

### Markers

Restaurants are rendered as simple MapLibre markers (not a vector layer).
Clicking a marker opens a popup with the restaurant name, cuisine, and a link
to the detail page. Restaurants without coordinates are silently omitted from
the map.

## Deployment Changes

- Add a `tiles_dir` variable to Ansible (`/opt/restaurants/tiles/`).
- Create the tiles directory in the playbook.
- Add the `/tiles/` nginx location block.
- Mount the tiles directory into the Docker container (for the management
  command to write to).
- Install the `pmtiles` CLI binary on the server (or include it in the Docker
  image).

## Implementation Order

1. **Model changes** — add bbox to City, add lat/lng to Restaurant. Migrate.
2. **Google Places** — extend field mask, update `apply_place_data`. Re-fetch
   data.
3. **Tile infrastructure** — `fetch_tiles` management command, admin action,
   nginx config, Ansible changes.
4. **Vendor static assets** — download and commit MapLibre GL JS, pmtiles.js,
   basemaps.js, fonts, sprites.
5. **Frontend** — list/map tabs, map rendering, marker popups, filter
   integration.
