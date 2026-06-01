"""CLI terminal output (Rich) — 100-point scoring edition."""
from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from analyzer_core import DEFAULT_SCAN_UNIVERSE, analyze_all, reports_to_summary_df

DEFAULT_CLI_TICKERS = list(DEFAULT_SCAN_UNIVERSE[:5])


def main() -> None:
    console = Console()
    console.print(
        Panel(
            "自訂觀察清單 · 100 分制評分\n"
            "Web: streamlit run app.py",
            title="Dividend Safety Analyzer (CLI)",
            border_style="green",
        )
    )
    reports = analyze_all(DEFAULT_CLI_TICKERS)
    df = reports_to_summary_df(reports)
    table = Table(title="Summary", box=box.ROUNDED)
    for col in df.columns:
        table.add_column(str(col))
    for _, row in df.iterrows():
        table.add_row(*[str(v) for v in row])
    console.print(table)
    for r in reports:
        console.print(Panel(r.analyst_commentary, title=f"{r.symbol}"))


if __name__ == "__main__":
    main()
