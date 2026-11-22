"""Machine-readable output for list and report commands (#196): ``--csv``
and ``--json`` print the rows a command's table shows, for a script, a
spreadsheet or an AI to read exactly.

A command opts in with :func:`output_options` and, where it prints a table,
asks :func:`machine` first and hands its rows to :func:`emit` instead. The
rows are the data behind the table, not its cells: field names are the
table's column names as they are (stable, so a reader can rely on them),
amounts are dollars, not rounded to the table's whole dollars (to 15
significant digits, which drops float noise and nothing else), shares and
rates are fractions (0.25, not 25%), months and dates are ISO strings, and
a missing value is empty (CSV) or ``null`` (JSON). A value a command reads
from a data repo CSV and doesn't compute with is given as written there.

JSON is one object: what the command's heading line says (``title``,
``dollars``, ``source`` and the like, whichever it has) as fields, then
``columns`` and ``rows`` for a command with one table, or ``tables`` (by
name, each with its ``columns`` and ``rows``) for one that prints several.
CSV is the bare rows of one table under a header: a command with several
prints its first (main) one, and says on stderr what only JSON holds. Lines a command prints beside its
table (notes, hints, totals said in words) go to stderr, so stdout holds
only the data.
"""

from __future__ import annotations

import csv
import functools
import io
import json
import math
import sys
from collections.abc import Callable, Generator, Iterable, Mapping, Sequence
from contextlib import contextmanager, redirect_stdout
from contextvars import ContextVar
from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import click
import pandas as pd

if TYPE_CHECKING:
    from _typeshed import DataclassInstance


class Format(StrEnum):
    TABLE = "table"
    CSV = "csv"
    JSON = "json"


_FORMAT: ContextVar[Format] = ContextVar("_FORMAT", default=Format.TABLE)
_COLLECTED: ContextVar[dict[str, Table] | None] = ContextVar("_COLLECTED", default=None)


def current() -> Format:
    """The format the running command prints in."""
    return _FORMAT.get()


def machine() -> bool:
    """Whether the running command prints CSV or JSON instead of tables."""
    return _FORMAT.get() is not Format.TABLE


def output_options(fn: Callable[..., Any]) -> Callable[..., Any]:
    """``--csv`` and ``--json`` on a list or report command. The body reads
    the choice with :func:`machine`/:func:`current`, never as arguments, so
    a command gains them without its signature changing."""

    @functools.wraps(fn)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        as_csv = kwargs.pop("as_csv", False)
        as_json = kwargs.pop("as_json", False)
        if as_csv and as_json:
            raise click.UsageError("use one of --csv and --json")
        fmt = Format.CSV if as_csv else Format.JSON if as_json else Format.TABLE
        if fmt is not Format.TABLE and (kwargs.get("as_graph") or kwargs.get("graph_file")):
            # The chart would share stdout with the data, or hold the data
            # back behind it; a script wanting both asks twice.
            raise click.UsageError(f"--{fmt} prints the data alone; ask for the chart separately")
        token = _FORMAT.set(fmt)
        try:
            return fn(*args, **kwargs)
        finally:
            _FORMAT.reset(token)

    wrapped = click.option(
        "--json", "as_json", is_flag=True,
        help="Print the rows as JSON instead of a table: unrounded values under stable "
             "field names (the table's columns).",
    )(wrapped)
    return click.option(
        "--csv", "as_csv", is_flag=True,
        help="Print the rows as CSV instead of a table: unrounded values under the "
             "table's column names.",
    )(wrapped)


def note(message: str) -> None:
    """A line said beside a table: printed as usual with a table, and to
    stderr with CSV or JSON, which keep stdout for the data."""
    click.echo(message, err=machine())


def value(item: Any) -> Any:
    """``item`` as JSON holds it: a number unrounded, a missing value
    ``None``, a date or month ISO, a NumPy scalar its Python value."""
    if item is None:
        return None
    if isinstance(item, pd.Timestamp):
        return None if pd.isna(item) else item.date().isoformat()
    if isinstance(item, pd.Period):
        return str(item)
    if isinstance(item, (datetime, date)):
        return item.isoformat()
    if hasattr(item, "item") and not isinstance(item, (str, bytes)):
        item = item.item()  # NumPy scalar
    if isinstance(item, float):
        if math.isnan(item):
            return None
        # 15 significant digits, every one a double holds exactly: drops the
        # noise arithmetic leaves (110658.78999999998 is 110658.79) and keeps
        # far more than any table shows.
        item = float(f"{item:.15g}")
        return int(item) if item.is_integer() and abs(item) < 2**53 else item
    if isinstance(item, (bool, int, str)):
        return item
    if item is pd.NA or item is pd.NaT:
        return None
    if isinstance(item, (list, tuple)):
        return [value(i) for i in item]
    if isinstance(item, Mapping):
        return {str(k): value(v) for k, v in item.items()}
    return str(item)


def records(frame: pd.DataFrame) -> tuple[list[str], list[dict[str, Any]]]:
    """``frame``'s columns and rows, its index levels first (an unnamed one
    as ``index``), unless the index is only row numbers."""
    plain = (isinstance(frame.index, pd.RangeIndex) and frame.index.name is None
             and frame.index.start == 0 and frame.index.step == 1)
    if not plain:
        frame = frame.reset_index()
    columns = [str(c) for c in frame.columns]
    rows = [{c: value(v) for c, v in zip(columns, row, strict=True)}
            for row in frame.itertuples(index=False, name=None)]
    return columns, rows


def dollars(fields: Mapping[str, Any]) -> dict[str, Any]:
    """``fields`` with the store's units made plain: an ``x_cents`` field as
    ``x`` in dollars, an ``x_micros`` one as ``x`` in whole units."""
    out: dict[str, Any] = {}
    for key, item in fields.items():
        for suffix, scale in (("_cents", 100), ("_micros", 1_000_000)):
            if key.endswith(suffix):
                key = key.removesuffix(suffix)
                item = None if item is None else item / scale
                break
        out[key] = item
    return out


def from_items(items: Iterable[Any], kind: type[DataclassInstance]) -> Rows:
    """Instances of the dataclass ``kind`` as rows, through :func:`dollars`:
    its fields are the columns, even with no rows."""
    import dataclasses

    shown = Rows(list(dollars(dict.fromkeys(f.name for f in dataclasses.fields(kind)))))
    for item in items:
        shown.add(**dollars(dataclasses.asdict(item)))
    return shown


def from_rows(columns: Sequence[str], rows: Iterable[Sequence[Any]]) -> Rows:
    """Rows from a query's tuples under ``columns``, through :func:`dollars`."""
    shown = Rows(list(dollars(dict.fromkeys(columns))))
    for row in rows:
        shown.add(**dollars(dict(zip(columns, row, strict=True))))
    return shown


class Rows:
    """The rows of a table built a row at a time, as a list command does:
    ``columns`` fixes the fields and their order."""

    def __init__(self, columns: Sequence[str]) -> None:
        self.columns = list(columns)
        self.rows: list[dict[str, Any]] = []

    def add(self, **fields: Any) -> None:
        unknown = set(fields) - set(self.columns)
        if unknown:
            raise KeyError(f"not a column: {', '.join(sorted(unknown))}")
        self.rows.append({c: value(fields.get(c)) for c in self.columns})

    def __len__(self) -> int:
        return len(self.rows)


type Table = pd.DataFrame | Rows


@contextmanager
def collecting() -> Generator[dict[str, Table]]:
    """For a command that prints many sections, each its own way: with
    --csv or --json, what the body prints to stdout is dropped, and the
    tables it hands :func:`collect` gather in the dict yielded, for
    :func:`emit` once it's done. With a table, nothing changes. Enter it
    once the command has asked for any names it needs: a prompt in it
    would be dropped too."""
    tables: dict[str, Table] = {}
    if not machine():
        yield tables
        return
    token = _COLLECTED.set(tables)
    try:
        with redirect_stdout(io.StringIO()):
            yield tables
    finally:
        _COLLECTED.reset(token)


def collect(name: str, table: Table) -> None:
    """Inside :func:`collecting`, keep ``table`` (its raw values, not the
    cells printed) under ``name``; elsewhere, nothing."""
    tables = _COLLECTED.get()
    if tables is not None:
        tables[name] = table


def _columns_rows(table: Table) -> tuple[list[str], list[dict[str, Any]]]:
    return (table.columns, table.rows) if isinstance(table, Rows) else records(table)


def emit(table: Table | Mapping[str, Table], **meta: Any) -> None:
    """Print ``table`` (or several, by name) as the running command's
    format asks; ``meta`` (what its heading line says) goes into JSON."""
    fmt = current()
    if fmt is Format.TABLE:
        raise RuntimeError("emit() is for --csv and --json")
    single = table if isinstance(table, (pd.DataFrame, Rows)) else None
    tables: dict[str, Table] = {}
    if single is None:
        assert isinstance(table, Mapping)
        tables = dict(table)
    if fmt is Format.CSV:
        if single is None:
            if not tables:
                click.echo("nothing to print", err=True)
                return
            first, *rest = tables
            if rest:
                click.echo(f"--csv prints the {first} table; --json has {', '.join(rest)} too",
                           err=True)
            single = tables[first]
        _write_csv(*_columns_rows(single))
        return
    out: dict[str, Any] = {k: value(v) for k, v in meta.items() if v is not None}
    if single is not None:
        out["columns"], out["rows"] = _columns_rows(single)
    else:
        out["tables"] = {}
        for name, each in tables.items():
            columns, rows = _columns_rows(each)
            out["tables"][name] = {"columns": columns, "rows": rows}
    click.echo(json.dumps(out, indent=2, ensure_ascii=False, allow_nan=False))


def _write_csv(columns: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    writer = csv.writer(sys.stdout, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        # Booleans and nested values as JSON spells them, so the two agree.
        writer.writerow(["" if row[c] is None else
                         json.dumps(row[c]) if isinstance(row[c], (bool, list, dict)) else row[c]
                         for c in columns])
