"""CLI terminal output (Rich) — 100-point scoring edition."""
from __future__ import annotations

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from analyzer_core import TICKERS, analyze_all, reports_to_summary_df


def main() -> None:
    console = Console()
    console.print(
        Panel(
            "實戰持股：PFE, GIS, FLO, NOK, NVO\n"
            "100 分制 | Web: streamlit run app.py",
            title="Dividend Safety Analyzer (CLI)",
            border_style="green",
        )
    )
    reports = analyze_all()
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
