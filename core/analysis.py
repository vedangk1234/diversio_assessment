"""Validate identities and analyze the reporting hierarchy.

Pure Python: takes the SourceRow list produced by core.parsing and returns a
plain result object. Nothing here knows about HTTP, Django, or templates.

The pipeline is four small steps, in this order:
    validate_identity  -> which rows are accepted
    build_indexes      -> look up accepted employees by id and by email
    resolve_managers   -> attach each employee to its manager (or record why not)
    find_cycle_members -> which employees sit inside a reporting loop
"""

from collections import Counter


class ValidationError:
    """One problem with one source row, reported back to the user."""

    def __init__(self, row_number, employee_id, message):
        self.row_number = row_number
        self.employee_id = employee_id
        self.message = message

    def __repr__(self):
        return f"ValidationError(row={self.row_number}, message={self.message!r})"


class Employee:
    """An accepted row, plus whatever we learn about it during analysis."""

    def __init__(self, source_row):
        self.row_number = source_row.row_number
        self.employee_id = source_row.get("employee_id")
        self.name = source_row.get("employee_name")
        self.email = source_row.get("email")
        self.manager_id = source_row.get("manager_id")
        self.manager_email = source_row.get("manager_email")
        self.department = source_row.get("department")

        # Filled in by resolve_managers.
        self.manager = None  # Employee, or None
        self.has_manager_error = False
        self.direct_reports = []

    @property
    def is_root(self):
        """A root has no manager AND no unresolved manager reference.

        A row whose manager could not be resolved is deliberately not a root:
        we know it was meant to report to somebody, we just could not say whom.
        """
        return self.manager is None and not self.has_manager_error

    def __repr__(self):
        return f"Employee({self.employee_id!r}, row={self.row_number})"


class AnalysisResult:
    """Everything the preview page needs to render."""

    def __init__(self, total_rows, employees, errors, cycle_members):
        self.total_rows = total_rows
        self.employees = employees
        self.errors = errors
        self.cycle_members = cycle_members

    @property
    def accepted_count(self):
        return len(self.employees)

    @property
    def roots(self):
        return [e for e in self.employees if e.is_root]

    @property
    def managers(self):
        """Accepted employees who have at least one direct report.

        Sorted by report count descending so the biggest teams read first.
        """
        with_reports = [e for e in self.employees if e.direct_reports]
        return sorted(
            with_reports,
            key=lambda e: (-len(e.direct_reports), e.employee_id),
        )


def analyze(source_rows):
    """Run the full pipeline over parsed rows and return an AnalysisResult."""
    employees, errors = validate_identity(source_rows)
    by_id, by_email = build_indexes(employees)
    errors.extend(resolve_managers(employees, by_id, by_email))
    cycle_members = find_cycle_members(employees)

    # Errors are collected per phase, so sort to put them back in file order.
    errors.sort(key=lambda e: (e.row_number, e.message))

    return AnalysisResult(
        total_rows=len(source_rows),
        employees=employees,
        errors=errors,
        cycle_members=cycle_members,
    )


def validate_identity(source_rows):
    """Split rows into accepted Employees and identity errors.

    employee_id and email are both required and both must be unique. When a
    value is duplicated, EVERY row carrying it is rejected -- including the
    first one -- because we cannot tell which copy is the real record.
    """
    id_counts = Counter(
        row.get("employee_id") for row in source_rows if row.get("employee_id")
    )
    email_counts = Counter(row.get("email") for row in source_rows if row.get("email"))

    employees = []
    errors = []

    for row in source_rows:
        employee_id = row.get("employee_id")
        email = row.get("email")
        row_errors = []

        if not employee_id:
            row_errors.append("employee_id is required.")
        elif id_counts[employee_id] > 1:
            row_errors.append(
                f"employee_id '{employee_id}' appears on "
                f"{id_counts[employee_id]} rows and must be unique."
            )

        if not email:
            row_errors.append("email is required.")
        elif email_counts[email] > 1:
            row_errors.append(
                f"email '{email}' appears on {email_counts[email]} rows "
                "and must be unique."
            )

        if row_errors:
            for message in row_errors:
                errors.append(ValidationError(row.row_number, employee_id, message))
            # Not accepted: this row takes no part in the hierarchy at all, so
            # it can neither have a manager nor be found as one.
            continue

        employees.append(Employee(row))

    return employees, errors


def build_indexes(employees):
    """Index accepted employees by id and by normalized email.

    This is the first of the two hierarchy passes. Building both lookups before
    resolving anything is what lets a manager appear anywhere in the file --
    above or below the people who report to them.
    """
    by_id = {e.employee_id: e for e in employees}
    by_email = {e.email: e for e in employees}
    return by_id, by_email


def resolve_managers(employees, by_id, by_email):
    """Second pass: point each employee at its manager, or record an error.

    A manager problem never un-accepts a row. The employee still counts, still
    appears in the accepted total, and can still be somebody else's manager --
    it just contributes no reporting edge and is not treated as a root.
    """
    errors = []

    for employee in employees:
        manager_id = employee.manager_id
        manager_email = employee.manager_email

        if not manager_id and not manager_email:
            continue  # no manager claimed -> this employee is a root

        by_id_match = by_id.get(manager_id) if manager_id else None
        by_email_match = by_email.get(manager_email) if manager_email else None

        message = None
        if manager_id and by_id_match is None:
            message = (
                f"manager_id '{manager_id}' does not match any accepted employee."
            )
        elif manager_email and by_email_match is None:
            message = (
                f"manager_email '{manager_email}' does not match any accepted "
                "employee."
            )
        elif by_id_match and by_email_match and by_id_match is not by_email_match:
            # Both fields resolved, but to two different people. We refuse to
            # guess which one the HRIS meant.
            message = (
                f"manager_id '{manager_id}' points to "
                f"'{by_id_match.employee_id}' but manager_email "
                f"'{manager_email}' points to '{by_email_match.employee_id}'."
            )

        manager = by_id_match or by_email_match

        if message is None and manager is employee:
            message = "employee is listed as their own manager."

        if message is not None:
            employee.has_manager_error = True
            errors.append(
                ValidationError(employee.row_number, employee.employee_id, message)
            )
            continue

        employee.manager = manager
        manager.direct_reports.append(employee)

    return errors


def find_cycle_members(employees):
    """Return the employees that sit ON a reporting cycle.

    Each employee has at most one manager, so the resolved graph is a
    functional graph: every node has out-degree <= 1, and each connected piece
    is a set of trees hanging off either a root or a single cycle. That lets us
    walk each chain iteratively -- no recursion, so a 100k-deep chain is fine.

    One colour per employee:
        UNVISITED   -- not looked at yet
        IN_PROGRESS -- on the chain we are walking right now
        DONE        -- finished; its cycle membership is already decided

    Walking forward from a node we stop at a DONE node (that tail is already
    settled) or at an IN_PROGRESS node. Hitting IN_PROGRESS means we closed a
    loop, and only the nodes from that meeting point onward in the current walk
    are ON the cycle -- the ones before it merely report INTO it.

    O(n) time and O(n) space: each employee is pushed onto a walk exactly once
    and marked DONE exactly once.
    """
    UNVISITED, IN_PROGRESS, DONE = 0, 1, 2

    state = {}  # employee_id -> colour
    cycle_members = []

    for start in employees:
        if state.get(start.employee_id, UNVISITED) != UNVISITED:
            continue

        # Walk the manager chain from `start`, remembering the path so we can
        # slice out the cycle if the walk closes a loop.
        path = []
        position = {}  # employee_id -> index in path, for O(1) cycle slicing
        node = start

        while node is not None and state.get(node.employee_id, UNVISITED) == UNVISITED:
            state[node.employee_id] = IN_PROGRESS
            position[node.employee_id] = len(path)
            path.append(node)
            node = node.manager

        if node is not None and state[node.employee_id] == IN_PROGRESS:
            # Closed a loop within this walk: everything from the re-entry
            # point to the end of the path is on the cycle. Nodes before that
            # index feed into the cycle and are deliberately not flagged.
            cycle_members.extend(path[position[node.employee_id]:])

        # The rest of the path either dead-ends at a root, hits a manager error,
        # or feeds into an already settled chain. Either way, this walk is done.
        for member in path:
            state[member.employee_id] = DONE

    cycle_members.sort(key=lambda e: e.row_number)
    return cycle_members
