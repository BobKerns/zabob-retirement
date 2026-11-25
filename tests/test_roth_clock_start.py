"""When a Roth five-year clock starts (#257): a person's ``roth_clock_start``
in persons.csv, for a clock that began before any Roth IRA lot the scenario
holds, and a Roth IRA inherited from outside the household, which keeps the
decedent's clock, has no age test, and must be emptied within ten years."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from zabob.retirement.cli import main
from zabob.retirement.sim import engine
from zabob.retirement.sim.engine import RothLot, run_scenario
from zabob.retirement.sim.loader import LoadError, LoadResult, roth_clock_year

ROTH_ALICE, ROTH_BILL = "Asset_Roth_Alice", "Asset_Roth_Bill"  # both opened 2015-01-31
BROKERAGE, BROKERAGE_LOT = "Asset_Brokerage_Joint", "default"  # $300,000, $200,000 of it basis
BIRTHDATES = {"alice": date(1965, 3, 15), "bill": date(1967, 8, 20)}


def _clocks(load: Callable[[], LoadResult]) -> dict[str, RothLot]:
    with closing(sqlite3.connect(load().intent_path)) as con:
        lots = engine._roth_lots(con, BIRTHDATES)
        names = dict(con.execute(
            "SELECT m.id, a.name FROM account_lot m JOIN account a ON a.id = m.account_id").fetchall())
    return {names[lot]: roth for lot, roth in lots.items()}


def _run(load: Callable[[], LoadResult], runs_dir: Path) -> Path:
    return run_scenario(load().intent_path, runs_dir / "roth.sqlite3", run_by="T",
                        allow_dirty_data=True, allow_dirty_code=True)


def _warnings(run: Path) -> list[dict[str, object]]:
    with closing(sqlite3.connect(run)) as con:
        raw = con.execute(
            "SELECT json_extract(run_args_json, '$.inherited_roth_warnings') FROM simulation_run"
        ).fetchone()[0]
    return json.loads(raw) if raw else []


@pytest.mark.parametrize(("text", "year"), [
    ("", None), ("2009", 2009), ("2009-04", 2009), ("2009-04-15", 2009),
])
def test_roth_clock_start_is_a_year_or_a_dates_year(text: str, year: int | None) -> None:
    assert roth_clock_year(text) == year


@pytest.mark.parametrize("text", ["1997", "09", "2009-13", "2009-02-30", "soon"])
def test_roth_clock_start_refuses_what_is_not_a_roth_year(text: str) -> None:
    with pytest.raises(ValueError):
        roth_clock_year(text)


# ---------- a person's own clock ----------


@pytest.mark.parametrize(("start", "clock"), [
    ("2009", date(2009, 1, 1)),  # an earlier clock, from an account the scenario lacks
    ("2020-06-01", date(2015, 1, 1)),  # never later than a lot the scenario holds
])
def test_a_persons_roth_clock_start_is_the_earliest_of_it_and_their_lots(
    start: str, clock: date, update_person: Callable[..., None],
    load_test_copy: Callable[[], LoadResult],
) -> None:
    update_person("bill", roth_clock_start=start)
    clocks = _clocks(load_test_copy)
    assert clocks[ROTH_BILL].clock_start == clock
    assert clocks[ROTH_ALICE].clock_start == date(2015, 1, 1)  # one clock per person


def test_with_a_roth_clock_start_an_undated_lot_no_longer_means_the_clock_has_run(
    update_person: Callable[..., None], update_account: Callable[..., None],
    load_test_copy: Callable[[], LoadResult],
) -> None:
    update_account(ROTH_BILL, opened="")
    assert _clocks(load_test_copy)[ROTH_BILL].clock_start is None
    update_person("bill", roth_clock_start="2024")
    assert _clocks(load_test_copy)[ROTH_BILL].clock_start == date(2024, 1, 1)


def test_a_bad_roth_clock_start_fails_the_load(
    update_person: Callable[..., None], load_test_copy: Callable[[], LoadResult],
) -> None:
    update_person("bill", roth_clock_start="1990")
    with pytest.raises(LoadError, match="roth_clock_start '1990' is before Roth IRAs began"):
        load_test_copy()


def test_an_own_roth_lot_takes_no_roth_clock_start(
    update_account_value: Callable[..., None], load_test_copy: Callable[[], LoadResult],
) -> None:
    update_account_value(ROTH_BILL, "default", roth_clock_start="2009")
    with pytest.raises(LoadError, match="only for an inherited_roth_ira lot"):
        load_test_copy()


# ---------- a Roth IRA inherited from outside the household ----------


def test_an_inherited_roth_keeps_the_decedents_clock_apart_from_the_owners(
    add_inherited_roth: Callable[..., str], load_test_copy: Callable[[], LoadResult],
) -> None:
    name = add_inherited_roth(roth_clock_start="2024", acquired="2026-01-15")
    clocks = _clocks(load_test_copy)
    assert clocks[name] == RothLot(
        basis_first=True, clock_start=date(2024, 1, 1), birthdate=None,
        inherited=True, empty_by=date(2036, 12, 31))
    assert clocks[ROTH_BILL].clock_start == date(2015, 1, 1)  # Bill's own is untouched


def test_an_inherited_roth_with_no_clock_start_has_run(
    add_inherited_roth: Callable[..., str], load_test_copy: Callable[[], LoadResult],
) -> None:
    name = add_inherited_roth()
    clock = _clocks(load_test_copy)[name]
    assert clock.clock_start is None and engine._roth_qualified(clock, date(2027, 1, 1))


@pytest.mark.parametrize(("when", "characters"), [
    # Bill is 59 in 2027: no age test, so only the decedent's clock matters.
    ("2027-01-31", ["tax_free", "roth_nonqualified"]),  # basis first, then earnings
    ("2029-01-31", ["tax_free"]),  # the clock started 2024 ran out 2029-01-01
])
def test_an_inherited_roth_is_taxed_on_the_decedents_clock_alone(
    when: str, characters: list[str], add_inherited_roth: Callable[..., str],
    append_calendar_row: Callable[..., None], load_test_copy: Callable[[], LoadResult],
    runs_dir: Path,
) -> None:
    name = add_inherited_roth(roth_clock_start="2024")
    append_calendar_row(date=when, kind="one_off_transfer", account_1=name, lot_1="default",
                        account_2="Asset_Checking", amount="30000.00")
    with closing(sqlite3.connect(_run(load_test_copy, runs_dir))) as con:
        legs = con.execute(
            "SELECT te.tax_character FROM transfer_event te JOIN account fa ON fa.id = te.from_account "
            "JOIN account ta ON ta.id = te.to_account "
            "WHERE fa.name = ? AND ta.name = 'Asset_Checking' ORDER BY te.id", (name,)).fetchall()
    assert [c for (c,) in legs] == characters


def test_an_inherited_roth_left_past_ten_years_is_flagged(
    add_inherited_roth: Callable[..., str], load_test_copy: Callable[[], LoadResult],
    runs_dir: Path,
) -> None:
    add_inherited_roth(acquired="2028-02-10")  # must be empty by 2038-12-31
    with pytest.warns(RuntimeWarning, match="after the ten-year deadline"):
        run = _run(load_test_copy, runs_dir)
    assert [(w["kind"], w["month"]) for w in _warnings(run)] == [("deadline", "2038-12-31")]
    explained = CliRunner().invoke(main, ["sim", "explain", str(run)])
    assert explained.exit_code == 0, explained.output
    assert "inherited Roth IRA warnings (1):" in explained.output


def test_an_inherited_roth_whose_deadline_passed_before_the_run_is_flagged_its_first_year(
    add_inherited_roth: Callable[..., str], retire_alice_csv: Callable[[str], Path],
    load_test_copy: Callable[[], LoadResult], runs_dir: Path,
) -> None:
    add_inherited_roth(acquired="2020-03-01")  # had to be empty by 2030-12-31
    path = retire_alice_csv("scenario.csv")
    path.write_text(path.read_text().replace(",2026-05-31,", ",2031-01-31,"))
    with pytest.warns(RuntimeWarning, match="after the ten-year deadline"):
        run = _run(load_test_copy, runs_dir)
    assert [(w["kind"], w["month"]) for w in _warnings(run)] == [("deadline", "2031-12-31")]


def test_an_inherited_roth_from_a_death_before_2020_has_no_deadline(
    add_inherited_roth: Callable[..., str], load_test_copy: Callable[[], LoadResult],
) -> None:
    # The SECURE Act's ten years cover deaths from 2020; earlier ones keep the stretch.
    name = add_inherited_roth(acquired="2019-06-01")
    assert _clocks(load_test_copy)[name].empty_by is None


def test_an_inherited_roth_emptied_in_time_is_not_flagged(
    add_inherited_roth: Callable[..., str], append_calendar_row: Callable[..., None],
    load_test_copy: Callable[[], LoadResult], runs_dir: Path,
) -> None:
    name = add_inherited_roth(acquired="2028-02-10")
    append_calendar_row(date="2038-06-30", kind="transfer_balance", account_1=name, lot_1="default",
                        account_2="Asset_Checking")
    assert _warnings(_run(load_test_copy, runs_dir)) == []


def test_money_moved_into_an_inherited_roth_is_flagged(
    add_inherited_roth: Callable[..., str], append_calendar_row: Callable[..., None],
    load_test_copy: Callable[[], LoadResult], runs_dir: Path,
) -> None:
    name = add_inherited_roth()
    append_calendar_row(date="2027-03-31", kind="one_off_transfer", account_1="Asset_Checking",
                        account_2=name, lot_2="default", amount="1000.00")
    with pytest.warns(RuntimeWarning, match="can't contribute to an inherited IRA"):
        run = _run(load_test_copy, runs_dir)
    assert [w["kind"] for w in _warnings(run)] == ["contribution"]


def test_money_sold_out_of_a_brokerage_lot_into_an_inherited_roth_is_flagged(
    add_inherited_roth: Callable[..., str], append_calendar_row: Callable[..., None],
    load_test_copy: Callable[[], LoadResult], runs_dir: Path,
) -> None:
    # A sale posts its basis and gain legs without net effects; still one warning.
    name = add_inherited_roth()
    append_calendar_row(date="2027-03-31", kind="one_off_transfer", account_1=BROKERAGE, lot_1=BROKERAGE_LOT,
                        account_2=name, lot_2="default", amount="1000.00")
    with pytest.warns(RuntimeWarning, match="can't contribute to an inherited IRA"):
        run = _run(load_test_copy, runs_dir)
    assert [w["kind"] for w in _warnings(run)] == ["contribution"]


def test_an_inherited_roth_rolled_into_the_owners_own_is_flagged(
    add_inherited_roth: Callable[..., str], append_calendar_row: Callable[..., None],
    load_test_copy: Callable[[], LoadResult], runs_dir: Path,
) -> None:
    name = add_inherited_roth()
    append_calendar_row(date="2027-03-31", kind="one_off_transfer", account_1=name, lot_1="default",
                        account_2=ROTH_BILL, lot_2="default", amount="1000.00")
    with pytest.warns(RuntimeWarning, match="can't roll it over"):
        run = _run(load_test_copy, runs_dir)
    assert [w["kind"] for w in _warnings(run)] == ["rollover"]


def test_an_inherited_roths_clock_cant_start_after_the_death(
    add_inherited_roth: Callable[..., str], load_test_copy: Callable[[], LoadResult],
) -> None:
    add_inherited_roth(acquired="2025-06-01", roth_clock_start="2026")
    with pytest.raises(LoadError, match="roth_clock_start 2026 is after the death"):
        load_test_copy()


def test_an_inherited_roth_needs_an_account_of_its_own(
    add_inherited_roth: Callable[..., str], add_account_value: Callable[..., None],
    load_test_copy: Callable[[], LoadResult],
) -> None:
    name = add_inherited_roth()
    add_account_value(name, lot="own", subkind="roth_ira", opening_balance="100.00")
    with pytest.raises(LoadError, match="needs an account of its own; its other lots are roth_ira"):
        load_test_copy()
