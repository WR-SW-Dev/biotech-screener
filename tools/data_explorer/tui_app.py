"""Data Explorer Shell — Textual TUI for operator-facing snapshot analysis.

Launch:
    python -m tools.data_explorer shell

Read-only. Does not modify production data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Markdown,
    TabbedContent,
    TabPane,
)

from tools.data_explorer.service import run_catalog, run_compare, run_daily, run_field, run_qa, run_top_n

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SNAPSHOTS_DIR = "data/snapshots"
TOP_N_DEFAULT = 30


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_snapshots_dir() -> Path:
    """Auto-detect the snapshots directory."""
    candidates = [
        Path(DEFAULT_SNAPSHOTS_DIR),
        Path("production_data/snapshots"),
    ]
    for c in candidates:
        if c.is_dir():
            return c
    return Path(DEFAULT_SNAPSHOTS_DIR)


def _snapshot_dates(snapshots_dir: Path) -> List[str]:
    """List snapshot dates, most recent first."""
    if not snapshots_dir.is_dir():
        return []
    return sorted(
        [d.name for d in snapshots_dir.iterdir() if d.is_dir() and len(d.name) >= 10 and d.name[:4].isdigit()],
        reverse=True,
    )


def _severity_color(exit_code: int) -> str:
    if exit_code == 0:
        return "green"
    if exit_code == 1:
        return "yellow"
    return "red"


def _severity_label(exit_code: int) -> str:
    return {0: "CLEAN", 1: "WARNINGS", 2: "ERROR"}.get(exit_code, "?")


# ---------------------------------------------------------------------------
# Snapshot picker modal
# ---------------------------------------------------------------------------


class SnapshotPickerScreen(ModalScreen[str]):
    """Modal to pick a snapshot date."""

    BINDINGS = [Binding("escape", "dismiss_modal", "Close")]

    def __init__(self, dates: List[str], title: str = "Pick snapshot") -> None:
        super().__init__()
        self._dates = dates
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-container"):
            yield Label(self._title, id="picker-title")
            yield ListView(
                *[ListItem(Label(d), name=d) for d in self._dates],
                id="picker-list",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

    def action_dismiss_modal(self) -> None:
        self.dismiss("")

    DEFAULT_CSS = """
    #picker-container {
        width: 40;
        height: 80%;
        margin: 2 4;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #picker-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #picker-list {
        height: 1fr;
    }
    """


# ---------------------------------------------------------------------------
# Field picker modal
# ---------------------------------------------------------------------------


class FieldPickerScreen(ModalScreen[str]):
    """Modal to pick a field name with filtering."""

    BINDINGS = [Binding("escape", "dismiss_modal", "Close")]

    def __init__(self, fields: List[str]) -> None:
        super().__init__()
        self._fields = fields

    def compose(self) -> ComposeResult:
        with Vertical(id="field-picker-container"):
            yield Label("Pick field", id="field-picker-title")
            yield Input(placeholder="Filter...", id="field-filter")
            yield ListView(
                *[ListItem(Label(f), name=f) for f in self._fields],
                id="field-list",
            )

    @on(Input.Changed, "#field-filter")
    def filter_fields(self, event: Input.Changed) -> None:
        q = event.value.lower()
        lv = self.query_one("#field-list", ListView)
        lv.clear()
        for f in self._fields:
            if q in f.lower():
                lv.append(ListItem(Label(f), name=f))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.name)

    def action_dismiss_modal(self) -> None:
        self.dismiss("")

    DEFAULT_CSS = """
    #field-picker-container {
        width: 50;
        height: 80%;
        margin: 2 4;
        background: $surface;
        border: thick $primary;
        padding: 1 2;
    }
    #field-picker-title {
        text-align: center;
        text-style: bold;
        margin-bottom: 1;
    }
    #field-list {
        height: 1fr;
    }
    """


# ---------------------------------------------------------------------------
# Main App
# ---------------------------------------------------------------------------


class DataExplorerApp(App):
    """Data Explorer Shell — read-only operator console."""

    TITLE = "Data Explorer Shell"
    CSS = """
    /* Top status bar */
    #status-bar {
        height: 3;
        dock: top;
        padding: 0 1;
        background: $primary-background;
    }
    #status-bar Label {
        margin: 0 1;
    }

    /* Main layout: 3 columns */
    #main-layout {
        height: 1fr;
    }

    /* Left pane: snapshot navigator */
    #left-pane {
        width: 24;
        border-right: tall $primary;
    }
    #left-pane Label.pane-title {
        text-style: bold;
        text-align: center;
        padding: 0 1;
        background: $primary;
        color: $text;
    }
    #snap-list {
        height: 1fr;
    }

    /* Center pane: tabbed content */
    #center-pane {
        width: 1fr;
    }

    /* Right pane: detail inspector */
    #right-pane {
        width: 36;
        border-left: tall $primary;
    }
    #right-pane Label.pane-title {
        text-style: bold;
        text-align: center;
        padding: 0 1;
        background: $primary;
        color: $text;
    }
    #detail-content {
        height: 1fr;
        padding: 1;
    }

    /* General tab content */
    .tab-content {
        padding: 1;
        height: 1fr;
    }

    /* Loading indicator */
    .loading {
        text-align: center;
        text-style: italic;
        color: $text-muted;
        padding: 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("1", "tab_daily", "Daily"),
        Binding("2", "tab_topn", "Top-N"),
        Binding("3", "tab_compare", "Compare"),
        Binding("4", "tab_qa", "QA"),
        Binding("5", "tab_field", "Field"),
        Binding("6", "tab_catalog", "Catalog"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "pick_prior", "Prior"),
        Binding("n", "set_n", "Set N"),
        Binding("f", "pick_field", "Field"),
        Binding("e", "export_json", "Export"),
    ]

    def __init__(self, snapshots_dir: Optional[Path] = None) -> None:
        super().__init__()
        self._snapshots_dir = snapshots_dir or _find_snapshots_dir()
        self._dates: List[str] = []
        self._current_date: str = ""
        self._prior_date: str = ""
        self._top_n: int = TOP_N_DEFAULT
        self._current_field: str = "coinvest_score_z"
        self._columns: List[str] = []
        # Cached responses
        self._last_resp: Dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Header()

        # Status bar
        with Horizontal(id="status-bar"):
            yield Label("Snapshot: --", id="st-snap")
            yield Label("Prior: --", id="st-prior")
            yield Label("QA: --", id="st-qa")
            yield Label("Overlap: --", id="st-overlap")
            yield Label("Artifacts: --", id="st-artifacts")

        # Main 3-column layout
        with Horizontal(id="main-layout"):
            # Left pane — snapshot navigator
            with Vertical(id="left-pane"):
                yield Label("Snapshots", classes="pane-title")
                yield ListView(id="snap-list")

            # Center pane — tabbed views
            with Vertical(id="center-pane"):
                with TabbedContent(id="tabs"):
                    with TabPane("Daily", id="tab-daily"):
                        yield VerticalScroll(
                            Markdown("*Loading...*", id="daily-content"),
                            classes="tab-content",
                        )
                    with TabPane("Top-N", id="tab-topn"):
                        yield VerticalScroll(
                            DataTable(id="topn-table"),
                            classes="tab-content",
                        )
                    with TabPane("Compare", id="tab-compare"):
                        yield VerticalScroll(
                            Markdown("*Select a prior snapshot with [p]*", id="compare-content"),
                            classes="tab-content",
                        )
                    with TabPane("QA", id="tab-qa"):
                        yield VerticalScroll(
                            Markdown("*Loading...*", id="qa-content"),
                            classes="tab-content",
                        )
                    with TabPane("Field", id="tab-field"):
                        yield VerticalScroll(
                            Markdown("*Press [f] to pick a field*", id="field-content"),
                            classes="tab-content",
                        )
                    with TabPane("Catalog", id="tab-catalog"):
                        yield VerticalScroll(
                            DataTable(id="catalog-table"),
                            classes="tab-content",
                        )

            # Right pane — detail inspector
            with Vertical(id="right-pane"):
                yield Label("Details", classes="pane-title")
                yield VerticalScroll(
                    Markdown("Select an item to inspect.", id="detail-content"),
                )

        yield Footer()

    def on_mount(self) -> None:
        self._dates = _snapshot_dates(self._snapshots_dir)
        self._populate_snap_list()
        if self._dates:
            self._current_date = self._dates[0]
            if len(self._dates) > 1:
                self._prior_date = self._dates[1]
            self._load_snapshot()

    # ------------------------------------------------------------------
    # Snapshot list
    # ------------------------------------------------------------------

    def _populate_snap_list(self) -> None:
        lv = self.query_one("#snap-list", ListView)
        lv.clear()
        for d in self._dates[:100]:
            lv.append(ListItem(Label(d), name=d))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.list_view.id == "snap-list":
            date = event.item.name
            if date and date != self._current_date:
                self._current_date = date
                self._load_snapshot()

    # ------------------------------------------------------------------
    # Data loading (run in workers to keep UI responsive)
    # ------------------------------------------------------------------

    @work(thread=True)
    def _load_snapshot(self) -> None:
        """Load all data for the current snapshot."""
        snap_path = str(self._snapshots_dir / self._current_date)

        # Daily
        try:
            resp = run_daily(snap_path)
            self._last_resp["daily"] = resp
            self.call_from_thread(self._update_daily, resp)
        except Exception as e:
            self.call_from_thread(self._set_markdown, "daily-content", f"**Error:** {e}")

        # QA
        try:
            resp = run_qa(snap_path)
            self._last_resp["qa"] = resp
            self.call_from_thread(self._update_qa, resp)
        except Exception:
            pass

        # Top-N
        try:
            resp = run_top_n(snap_path, n=self._top_n)
            self._last_resp["top-n"] = resp
            self.call_from_thread(self._update_topn, resp)
        except Exception:
            pass

        # Catalog
        try:
            resp = run_catalog(snap_path)
            self._last_resp["catalog"] = resp
            self.call_from_thread(self._update_catalog, resp)
        except Exception:
            pass

        # Columns (for field picker)
        try:
            from tools.data_explorer.loader import load_file

            p = Path(snap_path) / "rankings.csv"
            if p.exists():
                df = load_file(p)
                self._columns = sorted(df.columns.tolist())
        except Exception:
            pass

        # Compare if we have a prior
        if self._prior_date:
            try:
                resp = run_compare(
                    str(self._snapshots_dir / self._prior_date),
                    snap_path,
                    n=self._top_n,
                )
                self._last_resp["compare"] = resp
                self.call_from_thread(self._update_compare, resp)
            except Exception:
                pass

        # Field
        if self._current_field:
            try:
                resp = run_field(snap_path, self._current_field)
                self._last_resp["field"] = resp
                self.call_from_thread(self._update_field, resp)
            except Exception:
                pass

        # Status bar
        self.call_from_thread(self._update_status_bar)

    # ------------------------------------------------------------------
    # UI update methods (called from worker via call_from_thread)
    # ------------------------------------------------------------------

    def _set_markdown(self, widget_id: str, text: str) -> None:
        try:
            md = self.query_one(f"#{widget_id}", Markdown)
            md.update(text)
        except Exception:
            pass

    def _update_status_bar(self) -> None:
        self.query_one("#st-snap", Label).update(f"Snapshot: {self._current_date}")
        self.query_one("#st-prior", Label).update(f"Prior: {self._prior_date or '--'}")

        daily = self._last_resp.get("daily", {}).get("data", {})
        qa = daily.get("qa", {})
        exit_code = qa.get("exit_code", 0)
        label = _severity_label(exit_code)
        self.query_one("#st-qa", Label).update(f"QA: {label}")

        compare = daily.get("compare", {})
        if compare:
            self.query_one("#st-overlap", Label).update(f"Top-30: {compare.get('overlap_pct', '?')}%")
        else:
            self.query_one("#st-overlap", Label).update("Overlap: --")

        cat = daily.get("catalog", {})
        self.query_one("#st-artifacts", Label).update(f"Artifacts: {cat.get('artifact_count', '?')}")

    def _update_daily(self, resp: Dict[str, Any]) -> None:
        d = resp.get("data", {})
        lines = [f"# Daily Report: {d.get('snapshot_date', '?')}\n"]

        prior = d.get("prior_snapshot_date")
        if prior:
            lines.append(f"**Prior:** {prior}\n")

        summary = d.get("summary", {})
        lines.append(f"**Rows:** {summary.get('rows', '?')} | **Columns:** {summary.get('columns', '?')}\n")

        # QA
        qa = d.get("qa", {})
        exit_code = qa.get("exit_code", 0)
        label = _severity_label(exit_code)
        n_issues = qa.get("n_issues", 0)
        lines.append(f"## QA: {label} ({n_issues} issues)\n")
        sev = qa.get("severity_summary", {})
        if any(sev.values()):
            parts = [f"{k}: {v}" for k, v in sev.items() if v > 0]
            lines.append(f"{', '.join(parts)}\n")

        # Errors first
        for issue in qa.get("issues", []):
            if issue["severity"] == "error":
                lines.append(f"- **[ERROR]** {issue['check']}: {issue['detail']}")
        lines.append("")

        # Compare
        compare = d.get("compare")
        if compare:
            lines.append(
                f"## Top-30 Overlap: {compare.get('overlap_count', '?')} ({compare.get('overlap_pct', '?')}%)\n"
            )
            added = compare.get("added", [])
            removed = compare.get("removed", [])
            if added:
                lines.append(f"**Added:** {', '.join(added)}\n")
            if removed:
                lines.append(f"**Removed:** {', '.join(removed)}\n")

            drifts = compare.get("largest_rank_changes", [])
            if drifts:
                lines.append("### Largest Score Changes\n")
                lines.append("| Ticker | Field | Before | After | Delta |")
                lines.append("|--------|-------|--------|-------|-------|")
                for item in drifts[:10]:
                    for col, vals in item.get("deltas", {}).items():
                        lines.append(
                            f"| {item['ticker']} | {col} | "
                            f"{vals['before']:.4f} | {vals['after']:.4f} | "
                            f"{vals['delta']:+.4f} |"
                        )
                lines.append("")

        # Catalog
        cat = d.get("catalog", {})
        lines.append(f"## Artifacts: {cat.get('artifact_count', '?')}\n")
        for category, files in cat.get("by_category", {}).items():
            lines.append(f"**{category}:** {', '.join(files)}")
        lines.append("")

        self._set_markdown("daily-content", "\n".join(lines))

    def _update_qa(self, resp: Dict[str, Any]) -> None:
        d = resp.get("data", {})
        lines = [
            "# QA Report\n",
            f"**Rows:** {d.get('rows', '?')} | **Columns:** {d.get('columns', '?')}\n",
            f"**Issues:** {d.get('n_issues', 0)}\n",
        ]

        sev = d.get("severity_summary", {})
        if any(sev.values()):
            parts = [f"{k}: {v}" for k, v in sev.items() if v > 0]
            lines.append(f"**Severity:** {', '.join(parts)}\n")

        # Group by severity
        for sev_level in ("error", "warning", "info"):
            issues = [i for i in d.get("issues", []) if i["severity"] == sev_level]
            if issues:
                lines.append(f"## {sev_level.upper()} ({len(issues)})\n")
                for issue in issues:
                    lines.append(f"- **{issue['check']}**: {issue['detail']}")
                lines.append("")

        if d.get("n_issues", 0) == 0:
            lines.append("All checks passed.")

        self._set_markdown("qa-content", "\n".join(lines))

    def _update_topn(self, resp: Dict[str, Any]) -> None:
        d = resp.get("data", {})
        rows = d.get("rows", [])
        table = self.query_one("#topn-table", DataTable)
        table.clear(columns=True)

        if not rows:
            return

        cols = list(rows[0].keys())
        for col in cols:
            table.add_column(col, key=col)

        for row in rows:
            table.add_row(*[str(row.get(c, "")) for c in cols])

    def _update_compare(self, resp: Dict[str, Any]) -> None:
        d = resp.get("data", {})
        lines = [
            f"# Comparison: {d.get('snapshot_a', '?')} vs {d.get('snapshot_b', '?')}\n",
            f"**Rows:** A={d.get('n_rows_a', '?')} | B={d.get('n_rows_b', '?')}\n",
            f"**Top-{d.get('top_n', 30)} Overlap:** {d.get('overlap_count', '?')} ({d.get('overlap_pct', '?')}%)\n",
        ]

        added = d.get("added", [])
        removed = d.get("removed", [])
        if added:
            lines.append(f"**Added (in B, not A):** {', '.join(added)}\n")
        if removed:
            lines.append(f"**Removed (in A, not B):** {', '.join(removed)}\n")

        drifts = d.get("largest_rank_changes", [])
        if drifts:
            lines.append("## Largest Score Changes\n")
            lines.append("| Ticker | Field | Before | After | Delta |")
            lines.append("|--------|-------|--------|-------|-------|")
            for item in drifts[:15]:
                for col, vals in item.get("deltas", {}).items():
                    lines.append(
                        f"| {item['ticker']} | {col} | "
                        f"{vals['before']:.4f} | {vals['after']:.4f} | "
                        f"{vals['delta']:+.4f} |"
                    )
            lines.append("")

        schema = d.get("schema", {})
        if schema.get("only_in_a") or schema.get("only_in_b"):
            lines.append("## Schema Differences\n")
            if schema.get("only_in_a"):
                lines.append(f"**Only in A:** {', '.join(schema['only_in_a'][:10])}")
            if schema.get("only_in_b"):
                lines.append(f"**Only in B:** {', '.join(schema['only_in_b'][:10])}")

        self._set_markdown("compare-content", "\n".join(lines))

    def _update_field(self, resp: Dict[str, Any]) -> None:
        if not resp.get("ok"):
            self._set_markdown("field-content", "\n".join(resp.get("errors", ["Error"])))
            return

        d = resp.get("data", {})
        field = d.get("field", "?")
        lines = [f"# Field: {field}\n"]

        # Stats table
        lines.append("| Stat | Value |")
        lines.append("|------|-------|")
        for key in (
            "count",
            "missing_count",
            "missing_pct",
            "zero_count",
            "zero_pct",
            "unique_count",
            "mean",
            "std",
            "min",
            "p5",
            "p25",
            "median",
            "p75",
            "p95",
            "max",
        ):
            if key in d and d[key] is not None:
                lines.append(f"| {key} | {d[key]} |")
        lines.append("")

        top = d.get("top_values", [])
        if top:
            lines.append("## Top Values\n")
            lines.append("| Ticker | Value |")
            lines.append("|--------|-------|")
            for v in top:
                lines.append(f"| {v['ticker']} | {v['value']} |")
            lines.append("")

        bottom = d.get("bottom_values", [])
        if bottom:
            lines.append("## Bottom Values\n")
            lines.append("| Ticker | Value |")
            lines.append("|--------|-------|")
            for v in bottom:
                lines.append(f"| {v['ticker']} | {v['value']} |")
            lines.append("")

        self._set_markdown("field-content", "\n".join(lines))

    def _update_catalog(self, resp: Dict[str, Any]) -> None:
        d = resp.get("data", {})
        artifacts = d.get("artifacts", [])
        table = self.query_one("#catalog-table", DataTable)
        table.clear(columns=True)

        if not artifacts:
            return

        for col in ("name", "category", "description", "size_bytes"):
            table.add_column(col, key=col)

        for art in artifacts:
            size_kb = f"{art.get('size_bytes', 0) / 1024:.1f} KB"
            table.add_row(
                art.get("name", ""),
                art.get("category", ""),
                art.get("description", ""),
                size_kb,
            )

    def _update_detail(self, text: str) -> None:
        self._set_markdown("detail-content", text)

    # ------------------------------------------------------------------
    # Table row selection -> detail pane
    # ------------------------------------------------------------------

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        table = event.data_table
        row_key = event.row_key

        if table.id == "topn-table":
            row = table.get_row(row_key)
            cols = [c.label.plain if hasattr(c.label, "plain") else str(c.label) for c in table.columns.values()]
            detail = "## Ticker Detail\n\n"
            for col, val in zip(cols, row):
                detail += f"**{col}:** {val}\n\n"
            self._update_detail(detail)

        elif table.id == "catalog-table":
            row = table.get_row(row_key)
            detail = "## Artifact Detail\n\n"
            labels = ["Name", "Category", "Description", "Size"]
            for label, val in zip(labels, row):
                detail += f"**{label}:** {val}\n\n"
            self._update_detail(detail)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_tab_daily(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-daily"

    def action_tab_topn(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-topn"

    def action_tab_compare(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-compare"

    def action_tab_qa(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-qa"

    def action_tab_field(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-field"

    def action_tab_catalog(self) -> None:
        self.query_one("#tabs", TabbedContent).active = "tab-catalog"

    def action_refresh(self) -> None:
        if self._current_date:
            self._load_snapshot()

    def action_pick_prior(self) -> None:
        if not self._dates:
            return

        def on_pick(date: str) -> None:
            if date and date != self._prior_date:
                self._prior_date = date
                self._load_snapshot()

        self.push_screen(
            SnapshotPickerScreen(self._dates, "Pick prior snapshot"),
            on_pick,
        )

    def action_set_n(self) -> None:
        """Cycle through common N values."""
        options = [10, 20, 30, 50]
        try:
            idx = options.index(self._top_n)
            self._top_n = options[(idx + 1) % len(options)]
        except ValueError:
            self._top_n = 30
        self.notify(f"Top-N set to {self._top_n}")
        if self._current_date:
            self._load_snapshot()

    def action_pick_field(self) -> None:
        if not self._columns:
            self.notify("No columns available — load a snapshot first")
            return

        def on_pick(field: str) -> None:
            if field:
                self._current_field = field
                self._load_field()

        self.push_screen(FieldPickerScreen(self._columns), on_pick)

    @work(thread=True)
    def _load_field(self) -> None:
        snap_path = str(self._snapshots_dir / self._current_date)
        try:
            resp = run_field(snap_path, self._current_field)
            self._last_resp["field"] = resp
            self.call_from_thread(self._update_field, resp)
            self.call_from_thread(lambda: self.query_one("#tabs", TabbedContent).__setattr__("active", "tab-field"))
        except Exception as e:
            self.call_from_thread(self._set_markdown, "field-content", f"**Error:** {e}")

    def action_export_json(self) -> None:
        """Export the current view's response as JSON."""
        active_tab = self.query_one("#tabs", TabbedContent).active
        tab_map = {
            "tab-daily": "daily",
            "tab-topn": "top-n",
            "tab-compare": "compare",
            "tab-qa": "qa",
            "tab-field": "field",
            "tab-catalog": "catalog",
        }
        key = tab_map.get(active_tab, "")
        resp = self._last_resp.get(key)
        if not resp:
            self.notify("No data to export")
            return

        out_dir = Path("reports/data_explorer/exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{key}_{self._current_date}.json"
        out_path.write_text(json.dumps(resp, indent=2, default=str))
        self.notify(f"Exported: {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run_shell(snapshots_dir: Optional[str] = None) -> int:
    """Launch the TUI shell."""
    path = Path(snapshots_dir) if snapshots_dir else _find_snapshots_dir()
    app = DataExplorerApp(snapshots_dir=path)
    app.run()
    return 0
