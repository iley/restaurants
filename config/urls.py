from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import Http404, HttpResponse, StreamingHttpResponse
from django.urls import include, path


def _serve_tile(request, name):
    """Serve PMTiles with Range Request support (dev server only).

    PMTiles requires HTTP Byte Serving (Range requests) to fetch individual
    tiles from the archive. Django's dev server doesn't handle this, so we
    do it manually here. In production, nginx serves /tiles/ directly.
    """
    from pathlib import Path

    tile_path = Path(settings.TILES_DIR) / name
    if not tile_path.is_file():
        raise Http404

    file_size = tile_path.stat().st_size
    headers = {
        "Accept-Ranges": "bytes",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range",
    }

    range_header = request.META.get("HTTP_RANGE", "")
    if range_header.startswith("bytes="):
        ranges = range_header[6:].split("-")
        start = int(ranges[0]) if ranges[0] else 0
        end = int(ranges[1]) if ranges[1] else file_size - 1
        end = min(end, file_size - 1)
        length = end - start + 1

        f = open(tile_path, "rb")
        f.seek(start)
        data = f.read(length)
        f.close()

        response = HttpResponse(data, status=206, content_type="application/octet-stream")
        response["Content-Length"] = length
        response["Content-Range"] = f"bytes {start}-{end}/{file_size}"
    else:
        response = StreamingHttpResponse(
            open(tile_path, "rb"), content_type="application/octet-stream",
        )
        response["Content-Length"] = file_size

    for key, value in headers.items():
        response[key] = value
    return response


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('restaurants.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += [path("tiles/<path:name>", _serve_tile)]
