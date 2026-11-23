"""An HSA taxed like a brokerage account by a state that doesn't recognize
HSAs (#497): its lots pay yearly dividends and interest, track a basis of
contributions and reinvested payouts, and a withdrawal's gain over that basis
is recorded for the state alone."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from zabob.retirement.sim import registries
from zabob.retirement.sim.engine import run_scenario
from zabob.retirement.sim.loader import LoadResult, growth_rule_name

HSA = "Asset_HSA_Alice"
PAYOUT = growth_rule_name(HSA, "default", prefix="interest_")
GROWTH = growth_rule_name(HSA, "default")


def _query(db: Path, sql: str, *args: Any) -> list[tuple]:
    with closing(sqlite3.connect(db)) as con:
        return con.execute(sql, args).fetchall()


@pytest.fixture
def hsa_scenario(add_hsa: Callable[[str], None]) -> None:
    """Alice's HSA in California (``add_hsa``), withdrawn from in June 2027."""
    add_hsa("2027-06-30")


def _lot(run: Path, month: str) -> tuple[int, int]:
    return _query(run, (
        "SELECT ls.balance, ls.cost_basis FROM lot_state ls "
        "JOIN simulation_step s ON s.id = ls.step_id "
        "JOIN account_lot m ON m.id = ls.lot_id JOIN account a ON a.id = m.account_id "
        "WHERE a.name = ? AND s.month = ?"), HSA, month)[0]


def _paid(run: Path, rule: str, year: int) -> int:
    return _query(run, (
        "SELECT COALESCE(SUM(t.amount), 0) FROM transfer_event t "
        "JOIN scheduled_transaction r ON r.id = t.reason_id "
        "WHERE t.reason_kind = 'rule' AND r.name = ? AND substr(t.date, 1, 4) = ?"), rule, str(year))[0][0]


@pytest.mark.usefixtures("hsa_scenario")
def test_an_hsa_pays_out_tracks_a_basis_and_its_state_taxes_the_gain(
    load_test_copy: Callable[[], LoadResult], runs_dir: Path,
) -> None:
    result = load_test_copy()
    [(payer, character)] = _query(result.intent_path, (
        "SELECT a.name, s.tax_character FROM scheduled_transaction s "
        "JOIN chain c ON c.id = s.from_account JOIN account a ON a.id = c.account_id "
        "WHERE s.name = ?"), PAYOUT)
    # Paid from the HSA payout account, at the lot's own untaxed character.
    assert (payer, character) == (registries.HSA_PAYOUT_ACCOUNTS["ordinary"].name, "deferred")
    run = run_scenario(result.intent_path, runs_dir / "hsa.sqlite3", run_by="TEST",
                       allow_dirty_data=True, allow_dirty_code=True)

    # The payout buys into the lot; its appreciation doesn't.
    first = "2026-05-31"
    paid = _query(run, (
        "SELECT t.amount FROM transfer_event t JOIN scheduled_transaction r ON r.id = t.reason_id "
        "JOIN simulation_step s ON s.id = t.step_id WHERE r.name = ? AND s.month = ?"), PAYOUT, first)[0][0]
    assert paid == 1_000_000 * 2 // 100 // 12
    assert _lot(run, first)[1] == 600_000 + paid

    # The withdrawal, which posts before the month's payout, takes its share
    # of the basis; the rest is gain, for the state alone.
    before_balance, before_basis = _lot(run, "2027-05-31")
    june_paid = _query(run, (
        "SELECT t.amount FROM transfer_event t JOIN scheduled_transaction r ON r.id = t.reason_id "
        "JOIN simulation_step s ON s.id = t.step_id WHERE r.name = ? AND s.month = '2027-06-30'"),
        PAYOUT)[0][0]
    [(gain, term)] = _query(run, "SELECT amount, tax_character FROM hsa_gain")
    assert term == "ltcg"
    basis_out = before_basis * 300_000 // before_balance
    assert 0 < gain == 300_000 - basis_out
    assert _lot(run, "2027-06-30")[1] == before_basis - basis_out + june_paid

    summary = dict(_query(run, "SELECT bucket, amount FROM tax_year_summary WHERE year = 2027"))
    assert summary["state_hsa_dividends"] == _paid(run, PAYOUT, 2027)
    assert summary["state_capital_gain_difference"] >= gain - summary.get("federal_capital_loss_used", 0)

    # The after-tax drawdown prices the HSA's balance as traditional money
    # federally, and only its gain over basis for California.
    balance, basis = _lot(run, "2027-12-31")
    assert summary["federal_drawdown_base"] - summary["state_drawdown_base"] == basis
    assert balance > basis


def _hsa_context(cost_bases: dict[int, int | None]):
    """Lots 1 and 2 are HSAs, 3 is checking and 4 a growth counterparty."""
    from datetime import date

    from zabob.retirement.sim.engine import ChainGraph, RefillContext

    graph = ChainGraph(members={}, leaf_lot={}, minimum_of={}, refill_chain_of={},
                       refill_target_of={}, refill_amount_of={}, maximum_of={}, overflow_chain_of={})
    return RefillContext(
        graph, aux=None, chain_base_date=date(2026, 5, 31), inflation_factor_cache={},
        account_tax_treatment={1: "tax_deferred", 2: "tax_deferred", 3: "taxable", 4: "tax_deferred"},
        account_subkind={1: "hsa", 2: "hsa", 3: "cash", 4: "capital_gain"},
        account_name={1: "HSA_1", 2: "HSA_2", 3: "Checking", 4: "deferred_gains"},
        cost_bases=cost_bases, growth_sources=frozenset({4}), hsa=frozenset({1, 2}))


@pytest.mark.parametrize(("to_id", "gains", "basis_2"), [
    (3, [(-1_000_00,)], 0),        # out at a loss: half its $8,000 basis on $3,000
    (2, [], 4_000_00),             # into another HSA: its basis goes with it
])
def test_an_hsa_withdrawal_takes_its_share_of_the_basis(
    ledger_con: sqlite3.Connection, to_id: int, gains: list[tuple[int]], basis_2: int,
) -> None:
    from zabob.retirement.sim.engine import _post_transfer

    balances = {1: 6_000_00, 2: 0, 3: 0, 4: 0}
    kinds = {1: "asset", 2: "asset", 3: "asset", 4: "income"}
    ctx = _hsa_context({1: 8_000_00, 2: 0, 3: None})
    _post_transfer(ledger_con, balances, kinds, 1, "2026-06-30", 1, to_id, 3_000_00, "none", 1,
                   refill_ctx=ctx)
    assert ctx.cost_bases[1] == 4_000_00
    assert ctx.cost_bases[2] == basis_2
    assert ledger_con.execute("SELECT amount FROM hsa_gain").fetchall() == gains
    # A fall posted back to the growth counterparty spends no basis.
    _post_transfer(ledger_con, balances, kinds, 1, "2026-06-30", 1, 4, 1_000_00, "deferred", 1,
                   refill_ctx=ctx)
    assert ctx.cost_bases[1] == 4_000_00


def test_an_overdrawn_hsa_realizes_nothing_past_its_balance(ledger_con: sqlite3.Connection) -> None:
    """Money drawn past an HSA's balance (the run lets it go negative) had
    no growth: only what the lot held is weighed against its basis."""
    from zabob.retirement.sim.engine import _post_transfer

    balances = {1: 2_000_00, 2: 0, 3: 0, 4: 0}
    kinds = {1: "asset", 2: "asset", 3: "asset", 4: "income"}
    ctx = _hsa_context({1: 1_000_00, 2: 0, 3: None})
    with pytest.warns(RuntimeWarning, match="went negative"):
        _post_transfer(ledger_con, balances, kinds, 1, "2026-06-30", 1, 3, 5_000_00, "none", 1,
                       refill_ctx=ctx)
    _post_transfer(ledger_con, balances, kinds, 1, "2026-07-31", 1, 3, 1_000_00, "none", 1,
                   refill_ctx=ctx)
    # The $2,000 it held was $1,000 of gain; the rest, then and later, none.
    assert ledger_con.execute("SELECT amount FROM hsa_gain").fetchall() == [(1_000_00,)]
    assert ctx.cost_bases[1] == 0
