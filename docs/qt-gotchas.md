# Qt Gotchas

Six Qt/PyQt6 landmines we discovered the hard way during the UI
modernization rework. Each cost real time to diagnose. Read this before
touching tables with per-row coloring, custom selection rendering,
cells with embedded editor widgets, custom-painted `QGraphicsItem`s,
theme-driven colors in custom-painted widgets, or any tab cache derived
from `self.config`.

---

## 1. `QTableView::item` QSS rule silently breaks `setBackground`

### Symptom

You set a cell's background with `item.setBackground(color)` (or `setData(Qt.BackgroundRole, brush)`) and **nothing renders**. The cell stays at the table's default color regardless of how vibrant the brush is. No error, no warning. Tints applied via `_update_row_colors`-style iteration appear to do nothing.

### Cause

If the active stylesheet contains *any* rule scoped to `QTableView::item` — even just `padding: 6px 10px; border: none;` — Qt's `QStyleSheetStyle` takes over item rendering and silently ignores the per-item brush. This is documented Qt behavior and applies to `QTreeView::item` and `QListView::item` as well.

### Fix

Don't put a `QTableView::item` block in your stylesheet. Apply the equivalent visuals via the table's properties instead:

- Row height → `table.verticalHeader().setDefaultSectionSize(...)` or `apply_modern_table_style` (see `gui/widgets/modern_table.py`).
- Grid → `table.setShowGrid(False)`.
- Alternating rows → `table.setAlternatingRowColors(True)` and the table-level `alternate-background-color` property in QSS (which is fine — it's on `QTableView`, not `QTableView::item`).

Both `resources/themes/dark.qss` and `light.qss` carry a comment explaining why the `::item` block is intentionally absent. **Don't re-add it.**

### Why not just live with the override?

Because per-row group tints stop working everywhere — Fixtures, Configuration, Structure, anywhere `QTableWidget` is used.

---

## 2. `selection-background-color: rgba(...)` is silently rendered solid

### Symptom

You set `selection-background-color: rgba(33, 150, 243, 70)` in QSS expecting a translucent overlay so per-row tints stay visible when a row is selected. What renders is an opaque solid color that fully covers the underlying tint. The alpha is silently dropped.

Verified by pixel sampling: alpha 70 over a pink (255, 182, 193) cell produced ~(31, 87, 132) — a deep solid blue, not the expected ~(194, 173, 207) translucent blend.

### Cause

Qt's QSS engine accepts `rgba(...)` syntax but throws away the alpha channel before painting selections. The same color used as `background-color` on a regular widget *does* respect alpha; it's specifically the selection-rendering pipeline that ignores it.

### Fix

Two parts, both required:

1. **`GroupRowDelegate`** strips `State_Selected` before calling `super().paint(...)` so Qt doesn't fill the cell with the opaque selection brush — the cell's `BackgroundRole` tint then survives. The delegate paints **no** border itself.
2. **`RowOutlineTableWidget`** draws a single continuous outline around the entire selected row from a transparent overlay widget that sits on top of viewport children. Per-cell border painting can't span widget cells (see gotcha #3) — the overlay sidesteps that entirely.

Apply both to a table with:

```python
from gui.widgets.row_outline_table import RowOutlineTableWidget
from gui.widgets.group_row_delegate import GroupRowDelegate

self.table = RowOutlineTableWidget()
self.table.setItemDelegate(GroupRowDelegate(self.table))
self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
```

### Why not other approaches?

- **`setStyleSheet` with `QTableView::item:selected`** — would work, but adding any `QTableView::item` rule re-triggers gotcha #1.
- **`QPalette.setBrush(Highlight, alpha-color)`** — Qt's palette also treats selection brushes as solid colors; same dead end.
- **Keeping the rgba and accepting the solid fallback** — fully covers the tint, defeating the point.
- **Per-cell border in the delegate** (the previous approach) — invisible on cells with `setCellWidget` (gotcha #3), so the row reads as bordered text cells with gaps.

---

## 3. `setCellWidget` makes the widget replace the cell display

> **Resolved for the Fixtures tab (2026-07-12).** The tab was rebuilt to
> the North Star screen: the table is now pure read-only
> `QTableWidgetItem` display (all editing moved to the inspector panel),
> so it hosts no cell widgets at all. Tints come from `BackgroundRole`
> brushes, and selection rendering is handled by
> `RowOutlineTableWidget` + `GroupRowDelegate` (gotcha #2). The
> `tinted_table.py` / `tinted_rows_table.py` experiments were deleted
> with the rebuild. This entry stays as the reference for any FUTURE
> table that genuinely needs editable widgets in cells.

### Symptom

A QTableWidget cell that hosts a widget via `setCellWidget(row, col, widget)` doesn't show the cell's `QTableWidgetItem` background underneath. `item.setBackground(color)` on cells that have a widget set has no visible effect, even though the brush is recorded on the item.

### Cause

`setCellWidget` is documented as replacing the cell's display, not overlaying. Qt's delegate `paint()` is **not called** for cells that host a widget — the widget renders itself inside the cell rect, and that's what you see. Anything that would normally come from the delegate (selection background, item background, alternate-row color) is invisible in widget cells.

### Fix patterns

Pick one based on the use case:

#### Per-widget stylesheet (the former Fixtures-tab approach)

For each cell widget, set a stylesheet that includes the per-row tint:

```python
cell_widget.setStyleSheet(
    f"background-color: {color.name()}; color: {fg_hex};"
)
```

This merged with the global theme rule (Qt only overrides the conflicting properties), so border / padding stayed theme-styled. The visual read as "fields colored" rather than "row colored with fields embedded" — acceptable as an interim, but not perfect. This is what the rebuild replaced.

#### Wrap the widget in a styled container

Tried; doesn't work cleanly. `QSpinBox::up-button`, `QSpinBox::down-button`, `QComboBox::drop-down`, and the `QLineEdit` embedded inside an editable `QComboBox` all paint **opaque** sub-control backgrounds by default. Making the wrapper transparent doesn't help — the widget's sub-controls cover the wrapper's tint anyway. Setting all sub-controls transparent in QSS works visually but loses the affordance of "this is a clickable button".

(Historical: `gui/widgets/tinted_table.py` and
`gui/widgets/tinted_rows_table.py` were the experiments that didn't pan
out. They were deleted 2026-07-12 when the Fixtures tab went read-only,
since the delegate + overlay approach below is the settled answer.)

#### Selection outline via a viewport overlay (current approach)

For the *selection* outline specifically — separate from the per-row tint — `gui/widgets/row_outline_table.py::RowOutlineTableWidget` draws the outline from a transparent overlay widget that's a child of the viewport, raised above all cell-widget siblings. The overlay's `paintEvent` looks up `selectionModel().selectedIndexes()`, computes each row's `visualRect` from leftmost to rightmost visible column, and draws a single continuous `drawRect`. Because the overlay paints last (after viewport children), the outline survives across `setCellWidget` cells.

Trade-offs of the overlay:
- `setCellWidget` is overridden to call `_overlay.raise_()` after each insert — new cell widgets become viewport children stacked above existing siblings, so the overlay needs to be re-raised to stay on top.
- `paintEvent` calls `_overlay.update()` so any viewport repaint (selection change, scroll, data change) re-renders the outline correctly.
- The overlay is always sized to the viewport via `resizeEvent`.

#### Replace `setCellWidget` with a `QStyledItemDelegate` (or drop editing from the table entirely)

The proper Qt-native answer for the *tint* part: the column gets a delegate whose `createEditor` returns the spinbox/combo only when the user starts editing; in display mode, `paint` renders the value as text and the cell's `BackgroundRole` paints normally.

What the Fixtures tab actually did (2026-07-12): rather than write five delegates (Universe spin, Address spin, Mode combo, Group combo, Role combo), the rebuild removed editing from the table altogether — the table became pure read-only display and all editing moved to the inspector panel. With no widget cells left, `BackgroundRole` tints paint across the full cell rect for free, and there was never a "fields colored" problem to solve. The delegate route above is still the right pattern for a table that genuinely needs in-cell editing.

---

## 4. `viewport().update()` doesn't dirty individual `QGraphicsItem`s

### Symptom

You toggle a class-level flag that affects how every `QGraphicsItem`
of some type paints itself (e.g. `FixtureItem.show_orientation_axes = True`)
and call `view.viewport().update()` to ask the view to repaint. The
viewport repaints — `drawBackground` runs, `drawForeground` runs — but
the items keep their old appearance. The new state never shows up on
screen, even with `ViewportUpdateMode.FullViewportUpdate`.

This bit us specifically on the Stage tab's "Show orientation axes"
checkbox: the handler flipped the class flag and called
`viewport().update()`, but the axes never appeared in the live view.

### Cause

Each `QGraphicsItem` keeps its own bounding-rect-based dirty
tracking. `viewport().update()` schedules a paint event for the
viewport widget — that triggers `drawItems`, which then asks each
item whether it needs repainting. Toggling a class-level attribute
doesn't make any individual instance dirty, so each item answers "no,
nothing about *me* changed" and Qt re-uses the cached drawing.

`scene.render()` to a fresh `QImage` *does* show the new state
because that path forces every item to render — which is misleading
because it makes the bug invisible to a unit test that uses
`scene.render()` for verification but caught by an end-to-end test
that grabs `viewport().grab()`.

### Fix

When the change is "every instance now paints differently", invalidate
every instance:

```python
scene = self.stage_view.scene
for item in scene.items():
    item.update()
scene.update()  # belt-and-braces viewport invalidation
```

`item.update()` is the canonical "I changed, repaint me" signal.
`scene.update()` then covers viewport-level invalidation in one call
without the caller needing to know about FullViewportUpdate vs
MinimalViewportUpdate modes.

### Why not other approaches?

- **`viewport().update()` alone** — the original failure mode.
  `FullViewportUpdate` mode helps, but only with respect to scrolled
  regions, not with respect to per-item dirty tracking.
- **`scene.invalidate()`** — works, but the explicit `for item in
  scene.items(): item.update()` reads more clearly at the call site
  and matches the canonical Qt pattern.

---

## 5. Theme-driven colours in custom-painted widgets via `pyqtProperty` + `qproperty-*`

### Symptom

A widget that does its own painting (overrides `drawBackground` /
`paint` rather than letting QSS render its background) doesn't follow
the theme. The QSS file has the right colour values somewhere, but the
widget keeps drawing with whatever Python-side hardcoded `QColor` the
painter used.

We hit this on the Stage tab — `StageView.drawBackground` was painting
the stage rectangle with `QtGui.QColor(240, 240, 240)` regardless of
which theme was active.

### Cause

QSS rules like `background-color: #2d2d2d;` only work for widgets that
let Qt's stylesheet engine paint their background — i.e. widgets where
`drawBackground` defers to the style engine. Custom-painted widgets
do their own drawing in `drawBackground` / `paint` and read colours
from Python state, so QSS background-color rules never reach them.

### Fix

Declare colour properties on the widget as `pyqtProperty(QColor, ...)`
and let the QSS theme write them via `qproperty-<name>`. The
stylesheet engine calls the setter during widget polishing, the
setter stores the value, and `drawBackground` reads from the stored
value at paint time:

```python
# gui/StageView.py
class StageView(QtWidgets.QGraphicsView):
    def _get_stage_fill_color(self):
        return self._stage_fill_color

    def _set_stage_fill_color(self, color):
        self._stage_fill_color = QColor(color)
        self._on_theme_color_changed()  # invalidate viewport + items

    stageFillColor = pyqtProperty(QColor, _get_stage_fill_color, _set_stage_fill_color)

    def drawBackground(self, painter, rect):
        painter.setBrush(QtGui.QBrush(self._stage_fill_color))
        ...
```

```qss
/* resources/themes/dark.qss */
StageView {
    qproperty-stageFillColor: #2d2d2e;
    qproperty-fixtureTextColor: #e0e0e0;
    /* ... */
}
```

Adding a new theme is then a matter of filling in the `qproperty-*`
lines — no Python edit required. Centre red/blue axes inside the
plot are deliberately not part of this list — they're "data"
colours, not theme chrome.

### The lazy-polish gotcha

`qproperty-*` rules are applied during widget *polishing*, which
Qt does lazily on first show or when an existing stylesheet is
re-applied. A unit test that constructs the widget and reads the
property without ever calling `show()` will see the Python-side
fallback value, not the QSS value. Force it:

```python
view.style().unpolish(view)
view.style().polish(view)
```

### Hosting a `QGraphicsItem` in a styled view

`QGraphicsItem` instances aren't widgets, so they can't be QSS targets
themselves. For an item that needs theme colours (e.g. `FixtureItem`
drawing label text), walk up to the parent view via
`scene().views()[0]` and read the view's qproperty:

```python
def _theme_text_color(self):
    scene = self.scene()
    if scene is not None and scene.views():
        view = scene.views()[0]
        color = getattr(view, "fixtureTextColor", None)
        if color is not None and color.isValid():
            return color
    return QColor(0, 0, 0)  # safe fallback
```

### Why not other approaches?

- **Read the active palette via `QApplication.palette()`** — Qt's
  application palette is **not** updated by QSS. It stays at the
  platform default regardless of which theme stylesheet is active.
  Palette-based theming and QSS-based theming are separate worlds.
- **Read `ThemeManager.current()` and switch on the name** —
  introduces a Python-side conditional, defeats QSS as the single
  source of truth, and decoheres if `current()` returns `None`
  before the first `apply()` call.
- **Inline `setStyleSheet` per widget** — would work for the
  widget-background case but not for `drawBackground` (where the
  Python painter doesn't read QSS at all), and re-introduces the
  mess the modernization rework was supposed to eliminate.

---

## 6. Tab caches derived from `self.config` need invalidation on the same triggers as the config rebind ladder

### Symptom

The user loads a YAML config (or imports a workspace) and one tab
behaves as if the config were still empty: Auto tab produces no DMX,
the universe-mapping table is empty, the visualizer's fixture list is
stale, etc. Other tabs work fine — the bug is always tab-local.

This was the root cause behind every "Auto mode does nothing"
complaint we hit on 2026-05-08 — three independent bugs in this same
class.

### Cause

Every tab stores `self.config = config` in `__init__`. When the user
loads a new YAML, MainWindow does `self.config = Configuration.load(...)`
which **swaps the reference** to a brand-new `Configuration` object.
Each tab attribute keeps pointing at the *old* one until explicitly
rebound:

```python
# MainWindow._do_load_configuration
self.config = Configuration.load(file_path)
self.config_tab.config = self.config         # rebind tab 1
self.fixtures_tab.config = self.config        # rebind tab 2
self.stage_tab.config = self.config           # rebind tab 3
self.structure_tab.config = self.config       # rebind tab 4
self.shows_tab.config = self.config           # rebind tab 5
self.auto_tab.config = self.config            # rebind tab 6 — easy to miss!
```

Missing one tab in this ladder is the highest-frequency regression
in this codebase. *In-place* mutations of the existing `Configuration`
(Fixtures tab adding fixtures, Stage tab moving them) work fine —
the shared reference resolves the new state.

But that's only half the bug. Every tab also has *secondary caches*
derived from `self.config` at construction time. Each one needs the
same invalidation discipline:

| Cache                          | Invalidation trigger                       |
|--------------------------------|--------------------------------------------|
| `AutoTab._fixtures_loaded` flag | `update_from_config` should reload defs   |
| `AutoTab._universe_table` rows  | `update_from_config` should repopulate    |
| `AutoTab._submasters` widget    | `_rebuild_group_panels()` on group change |
| `AutoTab._riff_constraints`     | `_rebuild_group_panels()` on group change |
| `AutoTab._plane_combo` items    | `_populate_plane_combo()` on geometry chg |
| `*_tab.embedded_visualizer`     | `set_config(self.config)` on every swap   |
| `DMXManager.fixture_maps`       | rebuild on fixture set change             |

A one-shot "loaded once" flag is the trap to avoid: pre-fix
`AutoTab._fixtures_loaded` was `True` after the first activation
against the empty initial config, so loading a YAML afterwards never
re-ran the QXF scan. Audio meters kept ticking but no fixtures moved
and no colours changed.

### Fix

1. The ladder in `_do_load_configuration` must rebind **every** tab —
   add the next tab the moment you create it.
2. Each tab's `update_from_config()` is the right place to refresh
   the secondary caches. Don't gate on a "loaded once" flag.
3. Use cache-aware loaders (`get_cached_fixture_definitions`) so
   eager refresh stays cheap.

### Discoverability

Audit `setup_ui()` of every tab for `self.config.X` accesses that
build widget contents. Each one is a candidate for this bug. The
in-source landmark below has the master list.

---

## 7. A modal dialog in a test hangs the whole suite, silently

`QDialog.exec()` (and `QMenu.exec`, `QInputDialog.getText`,
`QFileDialog.getSaveFileName`, `QMessageBox.warning`, and the other
static convenience dialogs) spins its own event loop and blocks until a
human answers. The offscreen platform does not change this: there is no
human, so the loop runs forever. pytest shows no failure, no timeout,
no output; the process just sits there. One such test cost hours before
anyone looked at the process ages.

The trap is easy to spring indirectly. A test that only wanted to check
a signal connection:

```python
tab.stage_view.set_orientation_requested.emit([item])   # looks harmless
```

reaches the tab's real slot, which had just learned to open the
orientation dialog. The emit now blocks. The test never mentions a
dialog.

### Fix

An autouse fixture in `tests/conftest.py` (`_no_blocking_modals`)
monkeypatches `QDialog.exec` and the blocking statics to raise a named
`RuntimeError` instead of opening. A forgotten modal now fails in
milliseconds with the offending class name. Tests that legitimately
drive a dialog patch it out themselves (`patch.object(module,
"OrientationDialog", FakeDialog)`) so their own accept/reject path still
runs. The `tests/e2e/` harness has its own richer guard
(`tests/e2e/conftest.py::modals`) that records a handler per dialog and
answers it; the two coexist.

Rule of thumb: never let a test drive a code path that can open a modal
without either patching the dialog class or driving its
accept/reject/get* directly.

---

## In-source landmarks

- `gui/widgets/group_row_delegate.py` — strips `State_Selected` so the row tint survives selection
- `gui/widgets/row_outline_table.py` — overlay-based row-selection outline that spans widget cells
- `gui/widgets/modern_table.py` — `apply_modern_table_style` (the right way to set table visuals without `QTableView::item`); also centralises `setDefaultAlignment(AlignLeft|AlignVCenter)` so every table reads the same
- `resources/themes/{dark,light}.qss` — comments mark where the `::item` rule used to live; `StageView { qproperty-* }` block lives near the bottom and shows the canonical theme-driven custom-paint pattern
- `gui/tabs/fixtures_tab.py::_update_row_colors` — concrete example of per-row tinting that works around all three table gotchas at once
- `gui/StageView.py` — five `pyqtProperty(QColor)` declarations + the `_on_theme_color_changed` helper that invalidates viewport + items in lockstep
- `gui/tabs/stage_tab.py::_on_show_axes_changed` — canonical "every item changed, repaint each one" handler (gotcha #4)
- `gui/gui.py::_do_load_configuration` and `import_workspace` — the config-rebind ladder (gotcha #6); add new tabs here whenever you add a new tab
- `gui/tabs/auto_tab.py::update_from_config` — concrete example of a tab refreshing every secondary cache derived from `self.config`
