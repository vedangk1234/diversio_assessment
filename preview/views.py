"""The one view: upload a CSV (GET) and render its import preview (POST).

Django's whole job in this app is to receive the upload and render the result.
All parsing and hierarchy logic lives in the `core` package, which has no
Django imports and is tested directly.
"""

from django.shortcuts import render

from core.analysis import analyze
from core.parsing import CsvParseError, parse_csv


def import_preview(request):
    """GET -> upload form. POST -> analysis of the uploaded file."""
    if request.method != "POST":
        return render(request, "preview/upload.html")

    uploaded = request.FILES.get("csv_file")
    if uploaded is None:
        return _upload_error(request, "Please choose a CSV file to upload.")

    try:
        # Read the whole file into memory on purpose: nothing is persisted, and
        # the parser needs the raw bytes so it can strip a BOM before decoding.
        rows = parse_csv(uploaded.read())
        result = analyze(rows)
    except CsvParseError as exc:
        # Expected, user-fixable problems: bad encoding, missing headers, empty
        # file, malformed CSV. These render as a message, never a 500.
        return _upload_error(request, str(exc))
    except Exception:
        # Last-resort guard so an unforeseen bug still shows the user something
        # useful instead of a stack trace.
        return _upload_error(
            request,
            "The file could not be processed. Please check that it is a valid "
            "HRIS CSV export and try again.",
        )

    return render(
        request,
        "preview/result.html",
        {"result": result, "filename": uploaded.name},
    )


def _upload_error(request, message):
    """Re-render the upload form with an error, keeping a 400 status."""
    return render(request, "preview/upload.html", {"error": message}, status=400)
