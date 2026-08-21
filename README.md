# HRIS Import Preview

A small Django app that previews what an HRIS CSV import *would* do, without
importing anything. You upload a CSV, and it shows you the row counts, the
validation errors with their source line numbers, the root employees, each
manager's direct-report count, and anyone caught in a reporting cycle.

Nothing is persisted. There is no database — the file is parsed and analyzed in
memory and the result is rendered straight back to the browser.

## Setup and run

Requires Python 3.10+.

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python manage.py runserver
```

Then open <http://127.0.0.1:8000/> and upload a CSV. `sample_hris.csv` in this
repo is a good one to start with — it deliberately contains a missing manager,
an id/email conflict, and a three-person reporting cycle.

There is no `migrate` step, because there is no database.

## Tests

```bash
pytest
```

21 tests, all against the pure-Python `core` package — no browser, no Django
test runner, no database.

## How it is put together

The rule I followed: **Django only does upload and render.** Everything that
decides anything lives in `core/`, which imports no Django at all.

```
core/parsing.py    raw bytes -> normalized rows with source line numbers
core/analysis.py   normalized rows -> AnalysisResult
preview/views.py   one view: GET = upload form, POST = process and render
preview/templates/ upload.html, result.html
config/            Django project (settings, urls, wsgi)
tests/             pytest tests against core/
```

`core/analysis.py` is four small steps run in order by `analyze()`:

1. `validate_identity` — decides which rows are *accepted*.
2. `build_indexes` — indexes accepted employees by id and by lowercased email.
3. `resolve_managers` — attaches each employee to its manager, or records why not.
4. `find_cycle_members` — finds employees sitting on a reporting loop.

Steps 2 and 3 are separate on purpose: that two-pass split is what lets a
manager appear anywhere in the file, above or below the people reporting to them.

### The rules, stated plainly

**Identity (this is what "accepted" means).** `employee_id` and `email` are both
required, and both must be unique after normalization. When a value is
duplicated, *every* row carrying it is rejected — including the first
occurrence, since there is no basis for calling one of the copies the real
record. Rejected rows drop out of the analysis entirely: they cannot have a
manager and cannot be found as one.

**Managers.** A manager problem does **not** un-accept a row. Such an employee
still counts toward the accepted total and can still be somebody else's manager;
they just contribute no reporting edge, and they are **not** counted as a root —
we know they were meant to report to someone, we just could not say whom. An
error is reported when the manager cannot be found, when `manager_id` and
`manager_email` resolve to two different people, or when an employee manages
themselves.

**Cycles.** Only employees *on* the loop are flagged. Someone who reports *into*
a cycle is not a member of it.

### Normalization

Every value is trimmed. `email` and `manager_email` are lowercased, so a manager
referenced as `ADA.BOSS@EXAMPLE.COM` matches an employee stored as
`Ada.Boss@Example.com`. `employee_id` and `manager_id` stay **case-sensitive** —
HRIS ids can be meaningfully cased, and folding case there could silently merge
two distinct people.

Files are decoded with `utf-8-sig`, which strips a byte-order mark if one is
present (Excel likes to add one) and otherwise behaves like plain UTF-8.

### Source row numbers

The header is line 1, so the first data row is line 2. The number reported is
the physical line the record *starts* on, taken from the csv reader's own line
counter — so a quoted value containing newlines shifts subsequent row numbers
correctly instead of throwing the count off.

### Cycle detection

Each employee has at most one manager, so the resolved graph is a **functional
graph**: out-degree ≤ 1, meaning every connected piece is a set of trees hanging
off either a root or a single cycle.

Detection is a three-colour walk (`UNVISITED` / `IN_PROGRESS` / `DONE`), written
**iteratively** — no recursion, so a 100,000-deep reporting chain will not blow
the stack. Walking forward from a node we stop at a `DONE` node (that tail is
already settled) or an `IN_PROGRESS` one. Hitting `IN_PROGRESS` means we closed a
loop, and only the nodes from that re-entry point onward in the current path are
on the cycle — the ones before it are exactly the "reports into a cycle" case,
and are deliberately left unflagged.

### Complexity

**O(n) time and O(n) space** in the number of rows. Each phase is a single pass:
counting duplicates, building the two indexes, resolving managers (dict lookups),
and the cycle walk, where each employee is pushed onto a path exactly once and
marked `DONE` exactly once. Space is the parsed rows plus two dicts and the
colour map.

Measured on this machine, a 100,000-employee file takes about **0.25 s to parse
and 0.25 s to analyze**. The practical ceiling is memory, not time: the whole
file is held in memory by design, which is fine at 100k rows and is the tradeoff
called out under limitations below.

## Error handling

A malformed upload always renders a readable message on the upload page with a
400 status — never an unhandled exception or a 500. Covered: not a CSV, missing
required headers, undecodable bytes, an empty file, a header with no data rows,
and no file selected. `parse_csv` raises a single `CsvParseError` whose message
is written to be shown directly to the user, and the view has a final
catch-all so even an unforeseen bug degrades into a message rather than a stack
trace.

## Assumptions

- **Duplicates poison every copy.** All rows sharing a duplicated id or email are
  rejected, first occurrence included. Keeping the first would mean guessing.
- **A manager error is not an identity error.** The person exists and is real
  data; only the relationship is unusable. So they stay accepted, and stay
  available as a manager to others.
- **An unresolvable manager reference is not a root.** Rooting them would
  silently invent a top-level employee out of a data error.
- **Extra columns are ignored, short rows are padded** with empty strings, rather
  than being errors. HRIS exports routinely carry trailing junk columns.
- **Whitespace-only manager fields count as blank**, so `"  "` makes a root
  rather than a failed lookup.
- **When `manager_id` and `manager_email` are both given, they must agree.** On a
  conflict we report it rather than picking a winner.
- Rows that are entirely blank are skipped, not reported as errors.

## Known limitations

- **The whole file is held in memory.** Fine for the ~100k rows this targets, but
  a genuinely huge file would want streaming. Uploads are capped at 10 MB in
  settings to make that boundary explicit rather than accidental.
- **No persistence at all** — this previews an import, it does not perform one.
  There is no "confirm and commit" step.
- **Email is not format-validated.** Uniqueness and matching are checked;
  whether a string looks like an email is not. Nor are gmail-style dot/plus
  aliases normalized — `a.b@x.com` and `ab@x.com` are treated as different people.
- **Only the first error per category is reported per employee** for manager
  resolution: an employee gets one manager error, not a list.
- **The result page renders every row.** At 100k employees the managers table
  would be very long; a real tool would paginate.
- **Cycles are listed as a flat set of members**, not grouped into the individual
  loops they belong to. With multiple independent cycles you would see everyone
  in one list.
- No auth, no deployment config, no CSV export of the preview — all out of scope.

## Time spent

_TODO: approximately X hours._

## AI tools used

_TODO: list tools and how they were used._
