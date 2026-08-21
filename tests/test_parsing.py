"""Tests for core.parsing -- pure Python, no Django, no browser."""

import pytest

from core.parsing import CsvParseError, parse_csv

HEADER = "employee_id,employee_name,email,manager_id,manager_email,department\n"


def test_values_are_trimmed_and_emails_lowercased():
    raw = HEADER + " E1 , Ada Lovelace , ADA@Example.COM ,, BOSS@Example.COM ,Eng\n"

    rows = parse_csv(raw.encode("utf-8"))

    assert len(rows) == 1
    row = rows[0]
    assert row.get("employee_id") == "E1"  # trimmed but case preserved
    assert row.get("employee_name") == "Ada Lovelace"
    assert row.get("email") == "ada@example.com"
    assert row.get("manager_email") == "boss@example.com"


def test_utf8_bom_and_quoted_commas_are_handled():
    raw = (HEADER + 'E1,"Alvarez, Renee",e1@x.com,,,Ops\n').encode("utf-8-sig")

    rows = parse_csv(raw)

    # The BOM must not end up glued to the first header name.
    assert rows[0].get("employee_id") == "E1"
    assert rows[0].get("employee_name") == "Alvarez, Renee"


def test_row_number_counts_physical_lines_including_quoted_newlines():
    raw = (
        HEADER
        + 'E1,"Multi\nLine Name",e1@x.com,,,Eng\n'  # occupies lines 2 and 3
        + "E2,Second,e2@x.com,,,Eng\n"  # so this one starts on line 4
    )

    rows = parse_csv(raw)

    assert [r.row_number for r in rows] == [2, 4]


@pytest.mark.parametrize(
    "raw, expected_fragment",
    [
        (b"", "empty"),
        (b"   \n", "empty"),
        (HEADER.encode(), "no employee rows"),
        (b"name,age\nAda,36\n", "missing required column"),
        (b"\xff\xfe\x00bad bytes", "UTF-8"),
    ],
)
def test_malformed_uploads_raise_a_clear_error(raw, expected_fragment):
    with pytest.raises(CsvParseError) as exc_info:
        parse_csv(raw)

    assert expected_fragment.lower() in str(exc_info.value).lower()


def test_headers_may_appear_in_any_order():
    raw = (
        "department,email,employee_name,manager_email,manager_id,employee_id\n"
        "Eng,e1@x.com,Ada,,,E1\n"
    )

    rows = parse_csv(raw)

    assert rows[0].get("employee_id") == "E1"
    assert rows[0].get("department") == "Eng"
