"""Turn raw uploaded bytes into normalized rows.

Pure Python: no Django imports here, so the whole parse step is testable
without a request, a browser, or a settings module.
"""

import csv
import io

# The columns the HRIS export contract promises. Order does not matter.
REQUIRED_HEADERS = (
    "employee_id",
    "employee_name",
    "email",
    "manager_id",
    "manager_email",
    "department",
)

# Fields that identify a person by address and are therefore case-insensitive.
# employee_id / manager_id stay case-sensitive on purpose: HRIS ids can be
# meaningfully cased and we must not merge two distinct ids by folding case.
LOWERCASED_FIELDS = ("email", "manager_email")


class CsvParseError(Exception):
    """Raised for any upload we cannot turn into rows.

    The message is written to be shown directly to the end user, so the view
    can render it without translating exception types into prose.
    """


class SourceRow:
    """One data row plus the line number it came from in the uploaded file."""

    def __init__(self, row_number, values):
        self.row_number = row_number  # header is line 1, first data row is line 2
        self.values = values  # dict of header -> normalized string

    def get(self, field):
        return self.values.get(field, "")

    def __repr__(self):
        return f"SourceRow(row_number={self.row_number}, values={self.values!r})"


def decode(raw):
    """Decode uploaded bytes as UTF-8, tolerating a byte-order mark.

    'utf-8-sig' strips a leading BOM if present and behaves like plain UTF-8
    otherwise, so one codec covers both Excel exports and normal UTF-8 files.
    """
    if isinstance(raw, str):
        return raw
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CsvParseError(
            "The file could not be read as UTF-8 text. "
            "Please re-save it as a UTF-8 encoded CSV and try again."
        )


def parse_csv(raw):
    """Parse raw bytes/text into a list of SourceRow.

    Raises CsvParseError with a user-facing message for anything malformed.
    """
    text = decode(raw)

    if not text.strip():
        raise CsvParseError("The uploaded file is empty.")

    # newline="" lets the csv module handle quoted newlines itself rather than
    # having the reader see rows already split apart by universal newlines.
    reader = csv.reader(io.StringIO(text, newline=""))

    try:
        raw_header = next(reader)
    except StopIteration:
        raise CsvParseError("The uploaded file is empty.")
    except csv.Error as exc:
        raise CsvParseError(f"The file is not valid CSV: {exc}")

    header = [cell.strip().lower() for cell in raw_header]
    missing = [name for name in REQUIRED_HEADERS if name not in header]
    if missing:
        raise CsvParseError(
            "The file is missing required column(s): "
            + ", ".join(missing)
            + ". Expected headers: "
            + ", ".join(REQUIRED_HEADERS)
            + "."
        )

    rows = []
    # reader.line_num is the physical line the reader has consumed so far, so
    # after reading the header it points at line 1. A record that contains
    # quoted newlines advances line_num by more than one, which is exactly why
    # we track it instead of counting records: the row number we report always
    # matches the line you would jump to in a text editor.
    previous_line = reader.line_num
    try:
        for values in reader:
            record_start_line = previous_line + 1
            previous_line = reader.line_num
            # csv only skips lines that are completely empty; a row of nothing
            # but commas or spaces still arrives here, so drop it explicitly.
            if not any(cell.strip() for cell in values):
                continue
            rows.append(
                SourceRow(
                    row_number=record_start_line,
                    values=_normalize(header, values),
                )
            )
    except csv.Error as exc:
        raise CsvParseError(f"The file is not valid CSV: {exc}")

    if not rows:
        raise CsvParseError("The file has a header row but no employee rows.")

    return rows


def _normalize(header, values):
    """Zip a raw row against the header and clean each value.

    Short rows get empty strings for the missing tail; extra columns beyond the
    header are ignored rather than treated as an error, since HRIS exports
    often carry trailing junk columns.
    """
    normalized = {}
    for index, name in enumerate(header):
        value = values[index] if index < len(values) else ""
        value = value.strip()
        if name in LOWERCASED_FIELDS:
            value = value.lower()
        normalized[name] = value
    return normalized
