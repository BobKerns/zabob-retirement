"""``--csv`` and ``--json`` on list and report commands (#196): the rows a
table shows, unrounded, under stable field names, with nothing else on
stdout."""

from __future__ import annotations

import csv
import io
import json
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
    result = _sim("report", "gains", "--json", "--chart", "--runfile", str(report_run_file))
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
