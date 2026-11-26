"""``--csv`` and ``--json`` on list and report commands (#196): the rows a
table shows, unrounded, under stable field names, with nothing else on
stdout."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
import pandas as pd
import pytest
from click.testing import CliRunner, Result

from zabob.retirement.cli import main
from zabob.retirement.sim import output, reports
from zabob.retirement.sim.connection import RunConnection
from zabob.retirement.sim.types import DollarMode


def _sim(*args: str) -> Result:
    return CliRunner().invoke(main, ["sim", *args])


def _json(result: Result) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def _csv(result: Result) -> list[dict[str, str]]:
    assert result.exit_code == 0, result.output
    return list(csv.DictReader(io.StringIO(result.stdout)))


# ---------- the helper ----------


@click.command()
@click.option("--several", is_flag=True)
@output.output_options
def _demo(several: bool) -> None:
    frame = pd.DataFrame({"amount": [1234.5, float("nan")], "share": [0.25, 0.1 + 0.2]},
                         index=pd.Index([2030, 2031], name="year"))
    output.note("a note beside the table")
    if not output.machine():
        click.echo("a table")
        return
    if several:
        rows = output.Rows(["name", "flag", "tags"])
        rows.add(name="a", flag=True, tags=["x", "y"])
        output.emit({"years": frame, "names": rows}, title="demo")
    else:
        output.emit(frame, title="demo", dollars="nominal")


def test_json_gives_the_heading_columns_and_unrounded_rows() -> None:
    result = CliRunner().invoke(_demo, ["--json"])
    assert result.stderr == "a note beside the table\n"
    assert json.loads(result.stdout) == {
        "title": "demo", "dollars": "nominal", "columns": ["year", "amount", "share"],
        "rows": [{"year": 2030, "amount": 1234.5, "share": 0.25},
                 # 0.1 + 0.2 is 0.30000000000000004: float noise, not data.
                 {"year": 2031, "amount": None, "share": 0.3}],
    }


def test_csv_gives_bare_rows_with_blanks_for_missing_values() -> None:
    result = CliRunner().invoke(_demo, ["--csv"])
    assert result.stdout == "year,amount,share\n2030,1234.5,0.25\n2031,,0.3\n"


def test_several_tables_are_named_in_json_and_csv_prints_the_first() -> None:
    assert json.loads(CliRunner().invoke(_demo, ["--several", "--json"]).stdout)["tables"] == {
        "years": {"columns": ["year", "amount", "share"],
                  "rows": [{"year": 2030, "amount": 1234.5, "share": 0.25},
                           {"year": 2031, "amount": None, "share": 0.3}]},
        "names": {"columns": ["name", "flag", "tags"],
                  "rows": [{"name": "a", "flag": True, "tags": ["x", "y"]}]},
    }
    result = CliRunner().invoke(_demo, ["--several", "--csv"])
    assert result.stdout.splitlines()[0] == "year,amount,share"
    assert "--csv prints the years table; --json has names too" in result.stderr


def test_without_an_option_the_table_prints_as_before() -> None:
    assert CliRunner().invoke(_demo, []).stdout == "a note beside the table\na table\n"


def test_csv_and_json_together_are_refused() -> None:
    result = CliRunner().invoke(_demo, ["--csv", "--json"])
    assert result.exit_code == 2
    assert "use one of --csv and --json" in result.output


def test_values_are_json_values() -> None:
    import numpy as np

    assert output.value(np.int64(3)) == 3
    assert output.value(np.float64(2.0)) == 2
    assert output.value(pd.Timestamp("2030-01-31")) == "2030-01-31"
    assert output.value(pd.NaT) is None
    assert output.value(110658.78999999998) == 110658.79
    assert output.dollars({"balance_cents": 12345, "quantity_micros": 1_500_000, "name": "x"}) == {
        "balance": 123.45, "quantity": 1.5, "name": "x"}


def test_values_from_prices_divisions_and_timestamps() -> None:
    from decimal import Decimal

    assert output.value(Decimal("12.50")) == 12.5
    assert output.value(Decimal("3")) == 3
    assert output.value(float("inf")) is None
    assert output.value(pd.Timestamp("2030-01-31 09:30")) == "2030-01-31T09:30:00"


def test_a_filtered_frame_has_no_row_number_field() -> None:
    frame = pd.DataFrame({"x": [1, 2, 3]})
    columns, rows = output.records(frame[frame.x != 2])
    assert columns == ["x"]
    assert rows == [{"x": 1}, {"x": 3}]


def test_rows_refuse_a_field_that_is_not_a_column() -> None:
    rows = output.Rows(["a"])
    with pytest.raises(KeyError, match="not a column: b"):
        rows.add(a=1, b=2)


# ---------- reports ----------


def test_report_json_is_the_frame_unrounded(report_run_file: Path,
                                            report_run: RunConnection) -> None:
    found = _json(_sim("report", "income", "--json", "--dollars", "nominal",
                       "--runfile", str(report_run_file)))
    frame = reports.without_empty_groups(
        reports.flows_by_year(report_run, "income", mode=DollarMode.NOMINAL),
        keep={"total", reports.ECONOMIC_INCOME, reports.NET_WORTH_CHANGE})
    assert found["title"] == "income by category"
    assert found["dollars"] == "nominal"
    assert found["columns"] == ["year", *frame.columns]
    first = found["rows"][1]
    year = first["year"]
    assert first[reports.ECONOMIC_INCOME] == pytest.approx(frame.loc[year, reports.ECONOMIC_INCOME],
                                                            abs=1e-6)
    # Cents, not the table's whole dollars.
    assert any(isinstance(v, float) and v != round(v) for row in found["rows"] for v in row.values()
               if not isinstance(v, str))


def test_report_csv_has_the_json_columns(report_run_file: Path) -> None:
    rows = _csv(_sim("report", "tax", "--csv", "--runfile", str(report_run_file)))
    found = _json(_sim("report", "tax", "--json", "--runfile", str(report_run_file)))
    assert list(rows[0]) == found["columns"]
    assert len(rows) == len(found["rows"])


@pytest.mark.parametrize("args", [
    ("account", "history", "Asset_Brokerage_Joint", "--yearly"),
    ("report", "expenses", "--year", "2030"),
    ("report", "gains"),
    ("report", "spending"),
    ("report", "tax", "--reconciliation"),
])
def test_every_report_takes_json(report_run_file: Path, args: tuple[str, ...]) -> None:
    found = _json(_sim(*args, "--json", "--runfile", str(report_run_file)))
    assert found["rows"] and set(found["rows"][0]) == set(found["columns"])


def test_a_chart_with_json_is_refused(report_run_file: Path) -> None:
    result = _sim("report", "gains", "--json", "--graph", "--runfile", str(report_run_file))
    assert result.exit_code == 2
    assert "--json prints the data alone" in result.output


def test_networth_json_matches_the_table(report_run_file: Path) -> None:
    found = _json(_sim("networth", "--runfile", str(report_run_file), "--dollars", "nominal",
                       "--json"))
    assert found["columns"] == ["year", "net_worth", "deferred_tax", "unpaid_tax", "after_tax"]
    monthly = _csv(_sim("networth", "--runfile", str(report_run_file), "--dollars", "nominal",
                        "--monthly", "--pre-tax", "--csv"))
    assert list(monthly[0]) == ["month", "net_worth"]
    assert monthly[0]["month"].count("-") == 2


def test_explain_json_holds_the_run_and_its_tables(report_run_file: Path) -> None:
    found = _json(_sim("explain", str(report_run_file), "--json"))
    assert found["run"]["status"] == "succeeded"
    assert set(found["counts"]) == {"steps", "account_states", "transfers"}
    assert list(found["tables"])[0] == "net_worth"
    assert found["tables"]["net_worth"]["columns"] == ["year", "nominal", "cpi_constant"]
    assert found["tables"]["negative_balances"]["columns"][:2] == ["month", "account"]
    rows = _csv(_sim("explain", str(report_run_file), "--csv"))
    assert list(rows[0]) == ["year", "nominal", "cpi_constant"]


# ---------- lists ----------


@pytest.mark.parametrize("args", [
    ("account", "list"),
    ("account", "lot", "list"),
    ("scheduled", "list"),
    ("transfer", "list"),
    ("chain", "list"),
    ("calendar", "list"),
    ("person", "list"),
    ("series", "list"),
    ("ytd", "list"),
    ("guard-rail", "list"),
    ("scenario", "list"),
])
def test_every_list_takes_csv_and_json(test_data_dir: Path, args: tuple[str, ...]) -> None:
    data = ("--data-dir", str(test_data_dir))
    scenario = () if args == ("scenario", "list") else ("--scenario", "retire_alice")
    found = _json(_sim(*args, *data, *scenario, "--json"))
    assert found["rows"], found
    assert all(list(row) == found["columns"] for row in found["rows"])
    rows = _csv(_sim(*args, *data, *scenario, "--csv"))
    assert list(rows[0]) == found["columns"]
    assert len(rows) == len(found["rows"])


def test_account_list_gives_dollars_and_fractions(test_data_dir: Path) -> None:
    found = _json(_sim("account", "list", "--data-dir", str(test_data_dir),
                       "--scenario", "retire_alice", "--json"))
    checking = next(row for row in found["rows"] if row["name"] == "Asset_Checking")
    assert checking["opening_balance"] == 5000
    assert "annual_rate" in found["columns"] and "annual_rate_micros" not in found["columns"]


def test_scenario_list_json_marks_inherited_values(test_data_dir: Path) -> None:
    found = _json(_sim("scenario", "list", "--data-dir", str(test_data_dir), "--json"))
    by_name = {row["scenario"]: row for row in found["rows"]}
    assert by_name["retire_alice"]["parents"] == ["base"]
    assert by_name["base"]["start_inherited"] is False


def test_series_show_json_gives_rates_as_fractions(test_data_dir: Path) -> None:
    found = _json(_sim("series", "show", "cpi", "--data-dir", str(test_data_dir),
                       "--scenario", "retire_alice", "--json"))
    (table,) = found["tables"].values()
    assert table["columns"][:2] == ["from", "annual_rate"]
    assert all(0 < row["annual_rate"] < 1 for row in table["rows"])


def test_an_empty_list_says_so_on_stderr(test_data_dir: Path) -> None:
    result = _sim("strategy", "list", "retire_alice", "--data-dir", str(test_data_dir), "--json")
    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert "no strategies in retire_alice" in result.stderr


def test_tax_list_json_gives_each_jurisdictions_row(add_tax: Callable[..., Path],
                                                    test_data_dir: Path) -> None:
    add_tax()
    found = _json(_sim("tax", "list", "retire_alice", "--data-dir", str(test_data_dir), "--json"))
    assert found["columns"][:2] == ["jurisdiction", "kind"]
    assert [row["jurisdiction"] for row in found["rows"]] == ["federal"]


def test_scheduled_list_gives_null_for_what_a_rule_leaves_out(test_data_dir: Path) -> None:
    found = _json(_sim("scheduled", "list", "--data-dir", str(test_data_dir),
                       "--scenario", "retire_alice", "--json"))
    values = [row[c] for row in found["rows"] for c in ("from_lot", "to_lot", "end", "description")]
    assert "-" not in values and "" not in values


def test_explain_json_holds_every_table_it_prints(report_run_file: Path) -> None:
    found = _json(_sim("explain", str(report_run_file), "--json"))
    assert {"net_worth", "negative_balances"} <= set(found["tables"])
    assert "negative_balance_warnings" in found


# ---------- the rest (#682) ----------


@pytest.mark.parametrize("args", [
    ("scenario", "show", "retire_alice"),
    ("tags", "--scenario", "retire_alice"),
    ("tags", "items", "budget:*", "--scenario", "retire_alice"),
    ("lifespan", "check", "67"),
])
def test_every_show_takes_csv_and_json(report_run_file: Path, test_data_dir: Path,
                                       args: tuple[str, ...]) -> None:
    # report_run_file tags retire_alice's spending in role budget.
    data = ("--data-dir", str(test_data_dir))
    found = _json(_sim(*args, *data, "--json"))
    assert found["rows"], found
    assert all(list(row) == found["columns"] for row in found["rows"])
    rows = _csv(_sim(*args, *data, "--csv"))
    assert list(rows[0]) == found["columns"]
    assert len(rows) == len(found["rows"])


@pytest.mark.parametrize("args, first", [
    (("chain", "show", "--scenario", "retire_alice"), "steps"),
    (("ensemble", "factors", "retire_alice", "--varying"), "factors"),
    (("lifespan", "tables"), "files"),
    (("strategy", "kinds"), "kinds"),
    (("tax", "kinds"), "kinds"),
])
def test_every_several_table_command_takes_csv_and_json(test_data_dir: Path, args: tuple[str, ...],
                                                        first: str) -> None:
    data = ("--data-dir", str(test_data_dir))
    found = _json(_sim(*args, *data, "--json"))
    assert list(found["tables"])[0] == first
    for table in found["tables"].values():
        assert all(list(row) == table["columns"] for row in table["rows"])
    rows = _csv(_sim(*args, *data, "--csv"))
    assert list(rows[0]) == found["tables"][first]["columns"]
    assert len(rows) == len(found["tables"][first]["rows"])


def test_items_json_gives_each_event_unrounded(report_run_file: Path) -> None:
    found = _json(_sim("items", "--runfile", str(report_run_file), "--account", "Asset_Checking",
                       "--limit", "5", "--json"))
    assert found["title"] == "ledger events" and found["accounts"] == ["Asset_Checking"]
    assert found["columns"][0] == "event"
    assert len(found["rows"]) == 5 < found["events"]
    assert "balance" in found["columns"]
    result = _sim("items", "--runfile", str(report_run_file), "--limit", "5", "--csv")
    assert "run: " in result.stderr and "gave the first 5" in result.stderr
    assert len(_csv(result)) == 5


def test_tags_items_json_names_each_item(report_run_file: Path, test_data_dir: Path) -> None:
    found = _json(_sim("tags", "items", "budget:core", "--scenario", "retire_alice",
                       "--data-dir", str(test_data_dir), "--json"))
    assert {(row["item"], row["name"]) for row in found["rows"]} >= {
        ("account", "Expense_Living"), ("account", "Expense_Healthcare")}


def test_chain_show_json_gives_shares_as_fractions(test_data_dir: Path) -> None:
    found = _json(_sim("chain", "show", "--scenario", "retire_alice",
                       "--data-dir", str(test_data_dir), "--json"))
    steps = found["tables"]["steps"]["rows"]
    assert steps and all(0 < row["share"] <= 1 for row in steps)
    assert {"lots", "uses"} <= set(found["tables"])


def test_chain_show_mermaid_with_json_is_refused(test_data_dir: Path) -> None:
    # Before the scenario is read: one with no chains would otherwise print nothing.
    result = _sim("chain", "show", "--scenario", "no_such_scenario", "--data-dir",
                  str(test_data_dir), "--mermaid", "--json")
    assert result.exit_code == 2
    assert "--json prints the data alone" in result.output


@pytest.mark.slow
def test_draws_csv_file_with_json_is_refused(mc_batch: Path, runs_dir: Path, intent_dir: Path,
                                             tmp_path: Path) -> None:
    result = _ensemble(runs_dir, intent_dir, "draws", "--csv-file", str(tmp_path / "out.csv"), "--json")
    assert result.exit_code == 2
    assert "ask for --csv-file separately" in result.output


def test_attribution_json_gives_zero_where_a_quantile_lacks_a_key(
    oat_batch: Path, runs_dir: Path, intent_dir: Path,
) -> None:
    from zabob.retirement.sim import sensitivity

    found = _json(_ensemble(runs_dir, intent_dir, "sensitivity", "--attribute", "gift",
                            "--dollars", "nominal", "--json"))
    by_q = sensitivity.oat_attribution(oat_batch, "gift", dollars=DollarMode.NOMINAL)
    assert all(v is not None for row in found["rows"] for k, v in row.items() if k.startswith("@"))
    for q, table in by_q.items():
        column = f"@{q:g}"
        for row in found["rows"]:
            expected = table.loc[row["year"], row["key"]] if row["key"] in table.columns else 0.0
            assert row[column] == pytest.approx(expected, abs=1e-6)


def test_ensemble_factors_json_gives_the_tree_by_parent(test_data_dir: Path) -> None:
    found = _json(_sim("ensemble", "factors", "retire_alice", "--data-dir", str(test_data_dir),
                       "--varying", "--json"))
    factors = {row["factor"]: row for row in found["tables"]["factors"]["rows"]}
    roots = [name for name, row in factors.items() if row["parent"] is None]
    assert roots and all(factors[name]["rho"] is None for name in roots)
    assert all(row["parent"] in factors for row in factors.values() if row["parent"] is not None)


def test_lifespan_tables_json_gives_a_row_per_table_sex_and_age(test_data_dir: Path) -> None:
    found = _json(_sim("lifespan", "tables", "--data-dir", str(test_data_dir), "--json"))
    values = found["tables"]["values"]
    assert values["columns"] == ["table", "location", "sex", "age", "q", "expected"]
    first = values["rows"][0]
    assert first["age"] == 0 and first["sex"] in ("female", "male") and 0 < first["q"] < 1


def test_scenario_show_json_matches_scenario_list(test_data_dir: Path) -> None:
    shown = _json(_sim("scenario", "show", "retire_alice", "--data-dir", str(test_data_dir), "--json"))
    listed = _json(_sim("scenario", "list", "--data-dir", str(test_data_dir), "--json"))
    (row,) = shown["rows"]
    alice = next(r for r in listed["rows"] if r["scenario"] == "retire_alice")
    for field in ("start", "start_inherited", "end", "seed", "ensemble_size"):
        assert row[field] == alice[field]
    assert row["parent"] == "base" and row["load_order"][-1] == "retire_alice"


def test_kinds_json_lists_parameters_with_defaults(test_data_dir: Path) -> None:
    found = _json(_sim("strategy", "kinds", "--data-dir", str(test_data_dir), "--json"))
    params = found["tables"]["parameters"]["rows"]
    assert params and all(row["default"] is None for row in params if row["required"])
    assert any(row["default"] is not None for row in params)
    kinds = {row["kind"] for row in found["tables"]["kinds"]["rows"]}
    assert {row["kind"] for row in params} <= kinds


def _ensemble(runs_dir: Path, intent_dir: Path, command: str, *args: str) -> Result:
    extra = ("--intent-dir", str(intent_dir)) if command == "draws" else ()
    return _sim("ensemble", command, "retire_alice", "--runs-dir", str(runs_dir), *extra, *args)


@pytest.mark.parametrize("args, first", [
    ((), "rows"),
    (("--row", "gift"), None),
    (("--attribute", "gift", "--years", "2030"), None),
])
def test_sensitivity_takes_csv_and_json(oat_batch: Path, runs_dir: Path, intent_dir: Path,
                                        args: tuple[str, ...], first: str | None) -> None:
    found = _json(_ensemble(runs_dir, intent_dir, "sensitivity", *args, "--json"))
    assert found["batch"] == oat_batch.name
    table = found["tables"][first] if first else found
    assert table["rows"] and all(list(row) == table["columns"] for row in table["rows"])
    rows = _csv(_ensemble(runs_dir, intent_dir, "sensitivity", *args, "--csv"))
    assert list(rows[0]) == table["columns"] and len(rows) == len(table["rows"])


def test_sensitivity_json_gives_unrounded_deltas_and_fractional_shares(
    oat_batch: Path, runs_dir: Path, intent_dir: Path,
) -> None:
    from zabob.retirement.sim import sensitivity

    found = _json(_ensemble(runs_dir, intent_dir, "sensitivity", "--years", "2030",
                            "--dollars", "nominal", "--json"))
    rows = found["tables"]["rows"]["rows"]
    table = sensitivity.oat_table(sensitivity.oat_deltas(oat_batch, DollarMode.NOMINAL), 2030)
    gift = next(row for row in rows if row["row"] == "gift")
    assert gift["year"] == 2030
    assert gift["swing"] == pytest.approx(table.loc["gift", "swing"], abs=1e-6)
    assert sum(row["share"] for row in rows if row["share"] is not None) == pytest.approx(1)
    assert set(found["tables"]["ranks"]["columns"][1:]) <= {str(y) for y in range(2026, 2041)}


def test_sensitivity_correlation_json(mc_batch: Path, runs_dir: Path, intent_dir: Path) -> None:
    found = _json(_ensemble(runs_dir, intent_dir, "sensitivity", "--mode", "monte_carlo", "--json"))
    assert found["ranked_by"] in ("rho", "srrc") and found["members"] == 7
    assert list(found["tables"]) == ["rows", "scores", "status"]
    assert {"year", "row", "rho", "srrc", "prcc", "r2"} <= set(found["tables"]["rows"]["columns"])
    assert {row["row"] for row in found["tables"]["status"]["rows"]} == {"gift", "retire_bill_vary"}


@pytest.mark.parametrize("args, first", [
    ((), "nodes"),
    (("--node", "gift"), "draws"),
    (("--pair", "core_inflation,cpi_factor"), "pair_members"),
])
def test_draws_take_csv_and_json(mc_batch: Path, runs_dir: Path, intent_dir: Path,
                                 args: tuple[str, ...], first: str) -> None:
    found = _json(_ensemble(runs_dir, intent_dir, "draws", *args, "--json"))
    assert list(found["tables"])[0] == first
    table = found["tables"][first]
    assert table["rows"] and all(list(row) == table["columns"] for row in table["rows"])
    rows = _csv(_ensemble(runs_dir, intent_dir, "draws", *args, "--csv"))
    assert list(rows[0]) == table["columns"] and len(rows) == len(table["rows"])


def test_draws_json_summary_holds_the_batch(mc_batch: Path, runs_dir: Path, intent_dir: Path) -> None:
    found = _json(_ensemble(runs_dir, intent_dir, "draws", "--json"))
    assert (found["batch"], found["mode"], found["members"], found["seed"]) == (
        mc_batch.name, "monte_carlo", 8, 7)
    gift = next(row for row in found["tables"]["nodes"]["rows"] if row["node"] == "gift")
    assert gift["n"] == 7 and gift["drawn_p50"] is not None
    node = _json(_ensemble(runs_dir, intent_dir, "draws", "--node", "gift", "--json"))
    members = node["tables"]["draws"]["rows"]
    assert [row["member"] for row in members] == list(range(8))
    assert members[0]["is_base"] and not members[1]["is_base"]
