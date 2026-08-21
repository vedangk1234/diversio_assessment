"""Tests for core.analysis -- pure Python, no Django, no browser."""

from core.analysis import analyze
from core.parsing import parse_csv

HEADER = "employee_id,employee_name,email,manager_id,manager_email,department\n"


def analyze_csv(*data_rows):
    """Build a CSV from row strings, parse it, and analyze it."""
    return analyze(parse_csv(HEADER + "".join(row + "\n" for row in data_rows)))


def ids(employees):
    return sorted(e.employee_id for e in employees)


def errors_for(result, employee_id):
    return [e.message for e in result.errors if e.employee_id == employee_id]


def test_duplicate_email_invalidates_every_row_that_shares_it():
    result = analyze_csv(
        "E1,Ada,dupe@x.com,,,Eng",
        "E2,Bob,dupe@x.com,,,Eng",  # same email as E1
        "E3,Cleo,cleo@x.com,,,Eng",
    )

    # The FIRST occurrence is rejected too -- we cannot tell which is real.
    assert result.total_rows == 3
    assert result.accepted_count == 1
    assert ids(result.employees) == ["E3"]
    assert {e.row_number for e in result.errors} == {2, 3}


def test_duplicate_employee_id_invalidates_every_row_and_removes_them_as_managers():
    result = analyze_csv(
        "E1,Ada,ada@x.com,,,Eng",
        "E1,Bob,bob@x.com,,,Eng",  # duplicate id
        "E9,Cleo,cleo@x.com,E1,,Eng",  # tries to report to the duplicated id
    )

    assert ids(result.employees) == ["E9"]
    # A rejected row cannot be found as a manager, so E9 gets a manager error.
    assert "does not match any accepted employee" in errors_for(result, "E9")[0]
    # ...but E9 is still accepted, and is not a root.
    assert result.accepted_count == 1
    assert result.roots == []


def test_manager_resolves_by_email_regardless_of_letter_casing():
    result = analyze_csv(
        "E1,Ada,Ada.Boss@Example.com,,,Eng",
        "E2,Bob,bob@x.com,,ADA.BOSS@EXAMPLE.COM,Eng",
    )

    assert result.errors == []
    bob = next(e for e in result.employees if e.employee_id == "E2")
    assert bob.manager.employee_id == "E1"
    assert [m.employee_id for m in result.managers] == ["E1"]
    assert len(result.managers[0].direct_reports) == 1


def test_manager_may_appear_after_their_reports_in_the_file():
    result = analyze_csv(
        "E2,Bob,bob@x.com,E1,,Eng",  # report listed first
        "E1,Ada,ada@x.com,,,Eng",  # manager listed second
    )

    assert result.errors == []
    assert ids(result.roots) == ["E1"]
    assert len(result.managers[0].direct_reports) == 1


def test_manager_id_and_email_pointing_at_different_people_is_a_conflict():
    result = analyze_csv(
        "E1,Ada,ada@x.com,,,Eng",
        "E2,Bob,bob@x.com,,,Eng",
        "E3,Cleo,cleo@x.com,E1,bob@x.com,Eng",  # id says E1, email says E2
    )

    message = errors_for(result, "E3")[0]
    assert "points to" in message and "E1" in message and "E2" in message

    cleo = next(e for e in result.employees if e.employee_id == "E3")
    # Still accepted, but no edge and not a root.
    assert result.accepted_count == 3
    assert cleo.manager is None
    assert cleo.is_root is False
    assert ids(result.roots) == ["E1", "E2"]
    # Nobody gained a report from the conflicting row.
    assert result.managers == []


def test_matching_manager_id_and_email_resolve_cleanly():
    result = analyze_csv(
        "E1,Ada,Ada@x.com,,,Eng",
        "E2,Bob,bob@x.com,E1,ADA@X.COM,Eng",  # both fields, same person
    )

    assert result.errors == []
    bob = next(e for e in result.employees if e.employee_id == "E2")
    assert bob.manager.employee_id == "E1"


def test_self_manager_is_an_error_and_not_a_root():
    result = analyze_csv("E1,Ada,ada@x.com,E1,,Eng")

    assert "own manager" in errors_for(result, "E1")[0]
    assert result.accepted_count == 1
    assert result.roots == []
    assert result.cycle_members == []


def test_three_node_cycle_flags_exactly_those_three():
    result = analyze_csv(
        "A,Ann,a@x.com,C,,Research",  # A -> C
        "B,Ben,b@x.com,A,,Research",  # B -> A
        "C,Cal,c@x.com,B,,Research",  # C -> B, closing A -> C -> B -> A
        "D,Dee,d@x.com,A,,Research",  # reports INTO the cycle
        "E,Eve,e@x.com,D,,Research",  # reports into D, further downstream
    )

    assert result.errors == []
    assert ids(result.cycle_members) == ["A", "B", "C"]
    # Reporting into a cycle is not the same as being in one.
    assert "D" not in ids(result.cycle_members)
    assert "E" not in ids(result.cycle_members)
    # A cycle has no root: every member has a manager.
    assert result.roots == []


def test_cycle_detection_is_iterative_over_a_long_chain():
    """A 100k-deep chain must not blow the stack (no recursion allowed)."""
    rows = ["E0,Employee 0,e0@x.com,,,Eng"]
    rows += [f"E{i},Employee {i},e{i}@x.com,E{i - 1},,Eng" for i in range(1, 100_000)]

    result = analyze(parse_csv(HEADER + "".join(row + "\n" for row in rows)))

    assert result.accepted_count == 100_000
    assert result.cycle_members == []
    assert ids(result.roots) == ["E0"]


def test_manager_with_an_error_can_still_manage_someone_else():
    result = analyze_csv(
        "E1,Ada,ada@x.com,MISSING,,Eng",  # E1's own manager cannot be found
        "E2,Bob,bob@x.com,E1,,Eng",  # but E1 is still a valid manager for E2
    )

    ada = next(e for e in result.employees if e.employee_id == "E1")
    assert ada.has_manager_error is True
    assert len(ada.direct_reports) == 1
    assert [m.employee_id for m in result.managers] == ["E1"]
    assert result.roots == []


def test_both_manager_fields_blank_makes_a_root():
    result = analyze_csv(
        "E1,Ada,ada@x.com,,,Exec",
        "E2,Bob,bob@x.com,  ,  ,Exec",  # whitespace-only counts as blank
    )

    assert result.errors == []
    assert ids(result.roots) == ["E1", "E2"]


def test_missing_required_identity_fields_are_reported_with_the_source_row():
    result = analyze_csv(
        "E1,Ada,ada@x.com,,,Eng",
        ",Nameless,no-id@x.com,,,Eng",  # missing employee_id, source line 3
        "E3,Bob,,,,Eng",  # missing email, source line 4
    )

    assert result.accepted_count == 1
    assert sorted(e.row_number for e in result.errors) == [3, 4]
    assert "employee_id is required" in " ".join(e.message for e in result.errors)
    assert "email is required" in " ".join(e.message for e in result.errors)
