"""A state's benefit recapture (#549): ``state_recapture__<state>.csv`` rows
add to the tax as state AGI rises, taking back the benefit of the lower
brackets, Connecticut's 2% phase-out add-back and tax recapture (2024
CT-1040 Tables C and D, married filing jointly)."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

import pytest

from zabob.retirement.sim import registries
from zabob.retirement.sim.engine import TaxRule, _prepare_tax
from zabob.retirement.sim.loader import (
    _validate_optional_state_tables, _validate_state_recapture,
)
from zabob.retirement.sim.tax_api import Return, TaxError
from zabob.retirement.sim.taxes import common
from zabob.retirement.sim.taxes.state_base import Income
from zabob.retirement.sim.taxes.state_tables import StateTablesYear

Aux = dict[tuple[str, str | None], list[tuple[str, dict[str, Any]]]]

YEAR = 2026
DATED = f"{YEAR}-01-31"
STATE = "CT"
CHECKING, PENSION, PENSION_BILL = 1, 2, 3


def _row(floor: int, width: int, amount: int, step: int | None = 10_000,
         status: str = "MFJ") -> dict[str, Any]:
    return {"filing_status": status, "floor": floor * 100, "width": width * 100,
            "amount": amount * 100, "step": None if step is None else step * 100}


CONNECTICUT = [
    _row(100_500, 50_000, 500, 5_000),  # Table C, the 2% phase-out add-back
    _row(210_000, 100_000, 500),        # Table D's three bands
    _row(400_000, 300_000, 5_400),
    _row(1_000_000, 90_000, 900),
]
"""Connecticut's 2024 recapture for a married couple filing jointly."""


@pytest.mark.parametrize(("agi", "added"), [
    (100_500, 0),
    (100_501, 50),          # Table C: more than $100,500 is the first $50
    (105_500, 50),
    (105_501, 100),
    (145_501, 500),
    (210_001, 500 + 50),    # Table D: more than $210,000, $50
    (300_000, 500 + 450),
    (300_001, 500 + 500),
    (399_999, 500 + 500),
    (400_001, 500 + 680),
    (690_000, 500 + 5_720),
    (999_999, 500 + 5_900),
    (1_000_001, 500 + 6_000),
    (1_080_001, 500 + 6_800),
    (5_000_000, 500 + 6_800),
])
def test_the_connecticut_tables_rise_in_steps(agi: int, added: int) -> None:
    assert common.recapture(CONNECTICUT, agi * 100) == added * 100


def test_without_a_step_it_rises_in_a_straight_line() -> None:
    rows = [_row(100_000, 50_000, 1_000, step=None)]
    assert common.recapture(rows, 100_000_00) == 0
    assert common.recapture(rows, 125_000_00) == 500_00
    assert common.recapture(rows, 200_000_00) == 1_000_00


@pytest.mark.parametrize(("payload", "message"), [
    ({"floor": 0, "width": 0, "amount": 1}, "width must be more than 0"),
    ({"floor": 0, "width": 100, "amount": 1, "step": 200}, "step must be more than 0"),
    ({"floor": 0, "width": 100, "amount": -1}, "amount"),
])
def test_the_loader_checks_a_recapture_row(payload: dict[str, Any], message: str) -> None:
    issues: list[str] = []
    _validate_state_recapture(
        [(registries.STATE_RECAPTURE, STATE, {"filing_status": "MFJ", **payload}, DATED)], issues)
    assert any(message in issue for issue in issues), issues


@pytest.fixture
def ledger(ledger_con: sqlite3.Connection,
           set_residence: Callable[..., None]) -> sqlite3.Connection:
    set_residence(ledger_con, (DATED, STATE, None))
    ledger_con.executemany(
        "INSERT INTO person(id, display, birthdate, role) VALUES (?, ?, ?, ?)",
        [("alice", "Alice", "1960-03-01", "primary"), ("bill", "Bill", "1962-07-01", "secondary")])
    ledger_con.executemany(
        "INSERT INTO account(id, name, kind, subkind, owner) VALUES (?, ?, ?, ?, ?)",
        [(CHECKING, "Asset_Checking", "asset", "cash", "joint"),
         (PENSION, "Income_Pension", "income", "pension", "alice"),
         (PENSION_BILL, "Income_Pension_Bill", "income", "pension", "bill")])
    return ledger_con


def _aux(recapture: bool, *, separate: bool = False) -> Aux:
    statuses = ("MFJ", "MFS", "Single")

    def flat(rate: int) -> list[tuple[str, dict[str, Any]]]:
        return [(DATED, {"filing_status": s, "floor": 0, "marginal_rate_micros": rate})
                for s in statuses]

    def amounts(amount: int) -> list[tuple[str, dict[str, Any]]]:
        return [(DATED, {"filing_status": s, "amount": amount}) for s in statuses]

    aux: Aux = {
        ("filing_status", None): [(DATED, {"filing_status": "MFJ"})],
        ("federal_brackets", None): flat(100_000),
        ("standard_deduction", None): amounts(0),
        ("capital_loss_limit", None): amounts(3_000_00),
        ("state_brackets", STATE): flat(50_000),
        (registries.STATE_STANDARD_DEDUCTION, STATE): amounts(0),
    }
    if recapture:
        aux[(registries.STATE_RECAPTURE, STATE)] = [(DATED, r) for r in CONNECTICUT]
    if separate:
        aux[(registries.STATE_SEPARATE_RETURN, STATE)] = [(DATED, {"allowed": "yes"})]
        aux[(registries.STATE_RECAPTURE, STATE)] += [
            (DATED, _row(100_000, 50_000, 100, step=None, status="MFS"))]
    return aux


def _prepared(con: sqlite3.Connection, aux: Aux) -> Any:
    federal_rule = TaxRule("federal", {"scope": "federal"}, 1)
    federal = _prepare_tax(con, {"scope": "federal"}, aux=aux, tax_year=YEAR, tid=1,
                           kind="federal").compute()
    assert federal.agi
    return _prepare_tax(con, {"scope": "state"}, aux=aux, tax_year=YEAR, tid=2,
                        kind="state_tables", jurisdictions={"federal": federal_rule})


def _state(con: sqlite3.Connection, aux: Aux) -> Return:
    return _prepared(con, aux).compute()


def test_the_recapture_is_added_to_the_tax_as_its_own_line(
    ledger: sqlite3.Connection, post_transfer: Callable[..., None],
) -> None:
    """$250,000 of pension: Table C's whole $500 and Table D's $200."""
    post_transfer(ledger, YEAR, PENSION, CHECKING, 250_000_00, "ordinary")
    plain = _state(ledger, _aux(recapture=False))
    with_it = _state(ledger, _aux(recapture=True))
    assert "recapture" not in plain.lines
    assert with_it["recapture"] == 700_00
    assert with_it["tax"] == plain["tax"] + 700_00


def test_a_separate_return_shows_each_spouses_recapture(
    ledger: sqlite3.Connection, post_transfer: Callable[..., None],
) -> None:
    """$125,000 each: a made-up MFS row recaptures $50 from each, less than
    the joint return's $700, so the separate return is taken, and its
    recapture is the line shown."""
    post_transfer(ledger, YEAR, PENSION, CHECKING, 125_000_00, "ordinary")
    post_transfer(ledger, YEAR, PENSION_BILL, CHECKING, 125_000_00, "ordinary")
    state = _state(ledger, _aux(recapture=True, separate=True))
    assert state["separate_return"] == 1
    assert state["separate_recapture_alice"] == state["separate_recapture_bill"] == 50_00
    assert state["recapture"] == 100_00
    assert state["joint_tax"] - state["tax"] == 600_00


class _Extends(StateTablesYear):
    """A household's tax step that adds to the built-in's."""

    def tax(self, taxable: int, income: Income) -> int:
        return super().tax(taxable, income) + 1_00


class _Replaces(StateTablesYear):
    """A household's tax step of its own, without the recapture."""

    def tax(self, taxable: int, income: Income) -> int:
        return common.progressive_tax(taxable, self.brackets)


class _Clashing(StateTablesYear):
    def tax_lines(self, taxable: int, income: Income) -> dict[str, int]:
        return {"agi": 1}


def test_the_line_follows_whether_the_tax_step_adds_the_recapture(
    ledger: sqlite3.Connection, post_transfer: Callable[..., None],
) -> None:
    post_transfer(ledger, YEAR, PENSION, CHECKING, 250_000_00, "ordinary")
    prepared = _prepared(ledger, _aux(recapture=True))
    assert _Extends(prepared.calc, prepared.ty).compute()["recapture"] == 700_00
    assert "recapture" not in _Replaces(prepared.calc, prepared.ty).compute().lines
    with pytest.raises(TaxError, match="tax line agi"):
        _Clashing(prepared.calc, prepared.ty).compute()


def _bracket_rows(*statuses: str) -> list[tuple[str, str | None, dict[str, Any], str]]:
    return [("state_brackets", STATE, {"filing_status": s, "floor": 0}, DATED) for s in statuses]


def test_the_loader_wants_every_status_the_brackets_have() -> None:
    """A survivor's Single year would otherwise recapture nothing."""
    issues: list[str] = []
    _validate_optional_state_tables(
        [*_bracket_rows("MFJ", "Single"),
         *((registries.STATE_RECAPTURE, STATE, r, DATED) for r in CONNECTICUT)], issues)
    assert any("state_recapture__CT.csv" in i and "Single" in i for i in issues), issues


def test_the_loader_wants_mfs_rows_where_spouses_may_file_separately() -> None:
    rows = [(registries.STATE_RECAPTURE, STATE, {**r, "filing_status": s}, DATED)
            for r in CONNECTICUT for s in ("MFJ", "Single")]
    issues: list[str] = []
    _validate_optional_state_tables(
        [*_bracket_rows("MFJ", "Single", "MFS"),
         (registries.STATE_SEPARATE_RETURN, STATE, {"allowed": "yes"}, DATED), *rows], issues)
    assert any("state_recapture__CT.csv" in i and "no MFS rows" in i for i in issues), issues
