"""The two common forms every source is read into (issue #527)."""

from __future__ import annotations

import csv
import dataclasses
import datetime as dt
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import pandas as pd

__all__ = [
    "Activity",
    "CORRECTS", "FLOW_COLUMNS", "ORIGIN", "REFERENCE", "REMOVES", "Budget", "BudgetLine", "Flows", "Holding",
    "Snapshot", "mask_account", "masked_flows", "masked_snapshot", "read_rows",
]


# What a holding is named (its ``asset``) when it is an account's cash, or
# what it has borrowed, beside its holdings that have symbols. No symbol is
# written so; its lot is the account's cash lot (the symbol ``CASH``), or one
# with no symbol. With a name of its own it can have a mapping row of its
# own, apart from the account's other holdings.
CASH = "(cash)"
MARGIN = "(margin)"
UNLISTED = frozenset({CASH, MARGIN})


@dataclass(frozen=True)
class Holding:
    """One thing an outside account holds. Only the account and a value are
    required; a source fills in what its file has."""

    account: str
    """The account's name as the source spells it."""
    value_cents: int
    """Signed as the source has it: a debt is usually negative."""
    asset: str = ""
    """A symbol, or a name ("House"); blank when the file gives one number
    for the whole account."""
    quantity: Decimal | None = None
    cost_basis_cents: int | None = None
    acquired: dt.date | None = None
    hints: Mapping[str, str] = field(default_factory=dict)
    """Whatever else the file says about the account (type, owner, tax
    treatment), for pre-filling a new account."""
    lot: str = ""
    """The lot this is for, where it is one part of a number the file gives
    whole and its mapping divides among lots (``lot_splits.csv``); no file
    says this."""

    @property
    def label(self) -> str:
        """``account``, or ``account / asset``: how a message names it."""
        return f"{self.account} / {self.asset}" if self.asset else self.account


@dataclass(frozen=True)
class Activity:
    """What a file says was posted to an account, beside its balance: enough
    to work the balance back to an earlier day (``holdings.at``)."""

    start: dt.date
    """The first day the file lists the account's transactions of."""
    end: dt.date
    """The last such day."""
    posted: tuple[tuple[dt.date, int], ...]
    """Each transaction's day and signed cents, money out negative."""


@dataclass(frozen=True)
class Snapshot:
    """Holdings as of one date."""

    source: str
    holdings: tuple[Holding, ...]
    as_of: dt.date | None = None
    """None when the file doesn't say."""
    notes: tuple[str, ...] = ()
    """What the reader guessed, or read without being sure of, for the
    user to check."""
    complete: frozenset[str] = frozenset()
    """The accounts (as ``Holding.account``) whose holdings the file says
    it lists every one of, where it says so apart from the holdings: an
    account listed in full that holds only cash, or nothing, has sold
    what an earlier file had."""
    activity: Mapping[str, Activity] = field(default_factory=dict)
    """By account (as ``Holding.account``), what was posted to it up to the
    file's date, where the file has that and the account's one holding is
    its balance. A bank's download is as of the day it was made and never
    of an earlier one; with this its balance on an earlier day is known."""
    dated: Mapping[dt.date, tuple[Holding, ...]] = field(default_factory=dict)
    """The holdings as of each date the file has them for, ``as_of`` among
    them, where it has more than one: a report over a period, with a set
    of columns for each of its dates (``holdings.nearest`` picks one)."""
    dated_notes: Mapping[dt.date, tuple[str, ...]] = field(default_factory=dict)
    """With ``dated``, what is to be said of one date's holdings only: the
    notes of the date picked join ``notes``."""
    unaccounted: Mapping[str, str] = field(default_factory=dict)
    """By account, why a file that could have such activity has none for
    it, as the end of a sentence: said where the balance was wanted as of
    an earlier day, so that it is never silently set as of the file's."""


FLOW_COLUMNS = (
    "source_row", "account", "date", "payee", "category", "transfer", "memo", "amount_cents",
)
"""What every source's transactions frame has: ``date`` a timestamp,
``amount_cents`` signed with money out negative, ``transfer`` non-blank for
a move between the household's own accounts, ``source_row`` the 1-based line
of the file (the row's place among them, where a file has no lines to
count by). A source may add columns of its own."""


ORIGIN = "origin"
"""The column naming each row's source, in transactions read from several."""
REFERENCE = "reference"
"""A column some sources add: the outside program's own id for a transaction,
the same in every file that has it."""
CORRECTS = "corrects"
"""A column some sources add, beside ``REFERENCE``: on a row that corrects
an earlier transaction of its account, that transaction's reference; blank
otherwise. ``sources.read_flows`` leaves out what a row corrects, and the
column."""
REMOVES = "removes"
"""With ``CORRECTS``: whether the row only removes what it corrects, and is
no transaction itself."""


@dataclass(frozen=True)
class Flows:
    """Transactions over a period, one row each (``FLOW_COLUMNS``)."""

    source: str
    """The source they were read from; of several, a label naming them all
    (joined by '+'), for a rule's provenance. Not to be taken apart: a
    source's name may have a '+' in it."""
    transactions: pd.DataFrame
    duplicates: int = 0
    """Rows left out because an earlier file of the run had them too, by
    their reference."""
    origins: tuple[str, ...] = ()
    """Each source the rows came from, in the order first met, when there
    are several."""
    notes: tuple[str, ...] = ()
    """What the reader guessed, or read without being sure of, for the
    user to check."""

    @property
    def sources(self) -> tuple[str, ...]:
        """Each source the rows came from, in the order first met."""
        return self.origins or (self.source,)

    def __post_init__(self) -> None:
        missing = [c for c in FLOW_COLUMNS if c not in self.transactions.columns]
        if missing:
            raise ValueError(f"{self.source}: transactions lack column(s) {missing}")


# An account number: digits, written whole ("123456789", "Z12345678") or in
# groups joined by a dash or a dot ("1234-5678") or by single spaces where
# each group is three or four digits ("4111 1111 1111 1111"), with up to
# three letters or a dash before it (an issuer's "-41001", its own last
# five). Bounded by digits, not by words, so "Account_123456789" and
# "ROTH12345678" are found too. It is one when it has five digits or more
# and isn't a date or a range of years; four or fewer are a year, a
# last-four already, or part of a date, and are left as they are.
_ACCOUNT_NUMBER = re.compile(
    r"(?<![0-9])(?:(?<![A-Za-z])[A-Za-z]{1,3}|-)?"
    r"(\d{3,4}(?: \d{3,4})+(?![-.]?\d)|\d+(?:[-.]\d+)*)(?![0-9])")
_NOT_A_NUMBER = re.compile(
    r"\d{4}[-.]\d{1,2}(?:[-.]\d{1,2})?|\d{1,2}[-.]\d{1,2}[-.]\d{2,4}|(?:19|20)\d\d-(?:19|20)\d\d")


def _mask_one(found: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", found.group(1))
    if len(digits) < 5 or _NOT_A_NUMBER.fullmatch(found.group(1)):
        return found.group(0)
    # After a mask's own "...", a longer run takes only the digits.
    return ("" if found.string.endswith("...", 0, found.start()) else "...") + digits[-4:]


def mask_account(name: str) -> str:
    """``name`` with every account number in it cut to its last four digits,
    as ``...1234``: what an outside account is called everywhere past the
    reader. A whole number reaches money; the last four only tell one
    account from another, which is all a mapping needs (issue #815).
    Idempotent: a masked name is its own mask."""
    return _ACCOUNT_NUMBER.sub(_mask_one, name)


def _masks(names: Iterable[str]) -> dict[str, str]:
    """Each of ``names`` and its mask. Two names of one file that would get
    one mask are refused: read as one, each would take the other's mapping."""
    masks: dict[str, str] = {}
    named: dict[str, str] = {}
    for name in dict.fromkeys(names):
        masked = masks[name] = mask_account(name)
        if named.setdefault(masked, name) != name:
            raise ValueError(
                f"two of its accounts would both be {masked!r} (an account number is kept to its last four "
                "digits), which no import can tell apart: kept apart, in separate files, they would share one "
                "mapping row. Set one of them by hand instead ('sim account lot edit'), and skip it here")
    return masks


def _masked_notes(notes: Iterable[str], masks: Mapping[str, str]) -> tuple[str, ...]:
    """``notes`` with each account name a reader wrote into them replaced by
    its mask. Not ``mask_account`` over the whole note, which would take an
    amount (``12345.00``) for a number."""
    whole = sorted((name for name, masked in masks.items() if name != masked), key=len, reverse=True)
    def masked(note: str) -> str:
        for name in whole:
            note = note.replace(name, masks[name])
        return note
    return tuple(masked(note) for note in notes)


def _masked_holding(holding: Holding, masks: Mapping[str, str]) -> Holding:
    hints = dict(holding.hints)
    if "account_name" in hints:
        hints["account_name"] = mask_account(hints["account_name"])
    return dataclasses.replace(holding, account=masks[holding.account], hints=hints)


def masked_snapshot(snapshot: Snapshot) -> Snapshot:
    """``snapshot`` with its outside accounts masked (``mask_account``)."""
    held = [h.account for h in (*snapshot.holdings, *(h for hs in snapshot.dated.values() for h in hs))]
    masks = _masks([*held, *snapshot.complete, *snapshot.activity, *snapshot.unaccounted])
    return dataclasses.replace(
        snapshot,
        holdings=tuple(_masked_holding(h, masks) for h in snapshot.holdings),
        complete=frozenset(masks[name] for name in snapshot.complete),
        activity={masks[name]: activity for name, activity in snapshot.activity.items()},
        dated={day: tuple(_masked_holding(h, masks) for h in held_then)
               for day, held_then in snapshot.dated.items()},
        unaccounted={masks[name]: why for name, why in snapshot.unaccounted.items()},
        notes=_masked_notes(snapshot.notes, masks),
        dated_notes={day: _masked_notes(said, masks) for day, said in snapshot.dated_notes.items()},
    )


def masked_flows(flows: Flows) -> Flows:
    """``flows`` with its outside accounts masked (``mask_account``): each
    row's account, and the account a transfer names."""
    frame = flows.transactions.copy()
    masks = _masks(name for name in frame["account"] if isinstance(name, str))
    frame["account"] = frame["account"].map(lambda name: masks.get(name, name) if isinstance(name, str) else name)
    frame["transfer"] = frame["transfer"].map(lambda name: mask_account(name) if isinstance(name, str) else name)
    return dataclasses.replace(flows, transactions=frame, notes=_masked_notes(flows.notes, masks))


@dataclass(frozen=True)
class BudgetLine:
    """What a budget plans for one category: its own amount, apart from
    any category under it."""

    income: bool
    """Money in; otherwise spending."""
    category: str
    """The category's whole path, its levels joined by ``:`` as the outside
    program's transactions name it (``Auto:Fuel``)."""
    total_cents: int
    """The period's amount. Spending is positive; a budgeted refund negative."""
    monthly_cents: tuple[int, ...] = ()
    """Each month's amount, in the order of ``Budget.months``; empty when
    the file has only the period's total."""


@dataclass(frozen=True)
class Budget:
    """A plan of income and spending by category over a period."""

    source: str
    lines: tuple[BudgetLine, ...]
    months: tuple[dt.date, ...] = ()
    """The first day of each month of the period, in order; empty when the
    file doesn't say which months it covers."""


def format_dollars(cents: int) -> str:
    """Format integer cents as the dollars-and-cents string account_lots.csv expects."""
    sign = "-" if cents < 0 else ""
    dollars, rem = divmod(abs(cents), 100)
    return f"{sign}{dollars}.{rem:02d}"


def read_rows(path: Path, limit: int | None = None) -> list[list[str]]:
    """The rows of an outside CSV file, or its first ``limit``: how every
    source reads one, so they agree on the encoding (a byte-order mark is
    not part of the first cell)."""
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        rows = []
        for row in csv.reader(fh):
            rows.append(row)
            if limit is not None and len(rows) >= limit:
                break
        return rows
