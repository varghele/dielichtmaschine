# gui/tabs/configuration_tab.py
"""Setup > Universes: output routing (North Star card 1d).

Layout: a card list (one row card per universe: UNI · NAME · OUTPUT ·
DESTINATION · CHANNELS USED · STATUS) with an inspector on the right
editing the selected universe. Protocol-irrelevant fields are not
disabled cells anymore - the inspector simply shows the page for the
selected output type, which is how the mockup solves the old
"mysteriously dead cells" problem.

Data contract unchanged: Universe.output = {'plugin', 'line',
'parameters': {...}} edited in place; gui.py still calls
update_from_config()/save_to_config().
"""

from PyQt6 import QtWidgets, QtCore
from PyQt6.QtGui import QBrush, QColor, QFont, QPainter
from PyQt6.QtCore import Qt, pyqtSignal

from config.models import Configuration, Universe
from utils.dmx_device_detection import (
    get_device_display_names, get_device_port_by_display_name,
)
from .base_tab import BaseTab

# Kept for import compatibility (FixturesTab and tests import these).
_DISABLED_FG = QBrush(QColor(127, 127, 127))
TOOLBAR_BTN_WIDTH = 40
TOOLBAR_BTN_SIZE = TOOLBAR_BTN_WIDTH
_TOOLBAR_BTN_WIDTH = TOOLBAR_BTN_WIDTH

PROTOCOLS = ("ArtNet", "E1.31", "DMX USB")

# Reference 03 puts the universe inspector at 420px.
INSPECTOR_WIDTH = 420

# The ArtNet "broadcast" destination convention (utils/artnet/README.md).
BROADCAST_IP = "255.255.255.255"

_PROTOCOL_DEFAULTS = {
    "ArtNet": {"ip": "192.168.1.100", "subnet": "0", "universe": "0"},
    "E1.31": {"multicast": "true", "ip": "239.255.0.1", "port": "5568",
              "universe": "1"},
    "DMX USB": {"device": ""},
}


def channels_used(config, universe_id: int) -> int:
    """Sum of the channel footprints patched into a universe."""
    total = 0
    for fixture in getattr(config, "fixtures", []) or []:
        if fixture.universe != universe_id:
            continue
        for mode in fixture.available_modes or []:
            if mode.name == fixture.current_mode:
                total += mode.channels
                break
    return total


def destination_summary(universe: Universe) -> str:
    """The mono one-liner describing where a universe goes."""
    protocol = universe.output.get("plugin", "E1.31")
    params = universe.output.get("parameters", {}) or {}
    if protocol == "ArtNet":
        ip = params.get("ip", "") or "no ip"
        return (f"{ip} · subnet {params.get('subnet', '0')} · "
                f"uni {params.get('universe', '0')} (0-based)")
    if protocol == "E1.31":
        uni = params.get("universe", "1")
        if (params.get("multicast", "true") or "true").lower() == "true":
            return f"multicast · uni {uni}"
        ip = params.get("ip", "") or "no ip"
        return f"{ip}:{params.get('port', '5568')} · uni {uni}"
    device = params.get("device", "")
    return device if device else "no device selected"


def is_ready(universe: Universe) -> bool:
    """Whether the output has its essential destination configured."""
    protocol = universe.output.get("plugin", "E1.31")
    params = universe.output.get("parameters", {}) or {}
    if protocol == "DMX USB":
        return bool(params.get("device"))
    return bool(params.get("ip"))


class StatusDot(QtWidgets.QWidget):
    """Small round status indicator (function color, painted - the
    theme fonts carry no dot glyph)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(9, 9)
        self._color = QColor("#5C6068")

    def set_ok(self, ok: bool) -> None:
        self._color = QColor("#4CAF50" if ok else "#5C6068")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QBrush(self._color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(self.rect().adjusted(1, 1, -1, -1))


class ChannelBar(QtWidgets.QWidget):
    """Channels-used meter: steel fill, accent when the row is
    selected (mockup behaviour)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(110, 6)
        self._fraction = 0.0
        self._selected = False

    def set_state(self, fraction: float, selected: bool) -> None:
        self._fraction = max(0.0, min(1.0, fraction))
        self._selected = selected
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2d2d2d"))
        painter.drawRect(self.rect())
        if self._fraction > 0:
            painter.setBrush(
                QColor("#F0562E" if self._selected else "#8D9299"))
            painter.drawRect(0, 0, int(self.width() * self._fraction),
                             self.height())


class UniverseRowCard(QtWidgets.QWidget):
    """One universe as a 1d row card. Display-only; editing happens in
    the inspector. Emits ``selected(universe_id)`` on click."""

    clicked = pyqtSignal(int)
    context_requested = pyqtSignal(int, QtCore.QPoint)

    # Shared grid so all cards + the header row align.
    COLUMN_WIDTHS = (52, 170, 110, -1, 190, 90)  # -1 = stretch

    def __init__(self, universe_id: int, parent=None):
        super().__init__(parent)
        from gui.typography import mono_font

        self.universe_id = universe_id
        self.setObjectName("UniverseCard")
        self.setProperty("role", "universe-card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(56)

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(12)

        self.uni_label = QtWidgets.QLabel(f"U{universe_id}")
        self.uni_label.setFont(mono_font(12))
        self.uni_label.setObjectName("UniverseCardId")
        self.uni_label.setFixedWidth(self.COLUMN_WIDTHS[0])
        layout.addWidget(self.uni_label)

        self.name_label = QtWidgets.QLabel("")
        font = self.name_label.font()
        font.setBold(True)
        self.name_label.setFont(font)
        self.name_label.setFixedWidth(self.COLUMN_WIDTHS[1])
        layout.addWidget(self.name_label)

        self.output_chip = QtWidgets.QLabel("")
        self.output_chip.setObjectName("UniverseCardOutput")
        self.output_chip.setProperty("role", "output-chip")
        self.output_chip.setFont(mono_font(9))
        self.output_chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.output_chip.setFixedWidth(self.COLUMN_WIDTHS[2])
        layout.addWidget(self.output_chip)

        self.destination_label = QtWidgets.QLabel("")
        self.destination_label.setFont(mono_font(9))
        self.destination_label.setObjectName("UniverseCardDestination")
        layout.addWidget(self.destination_label, 1)

        used_box = QtWidgets.QHBoxLayout()
        used_box.setSpacing(8)
        self.channel_bar = ChannelBar()
        used_box.addWidget(self.channel_bar)
        self.used_label = QtWidgets.QLabel("0/512")
        self.used_label.setFont(mono_font(9))
        self.used_label.setObjectName("UniverseCardUsed")
        used_box.addWidget(self.used_label)
        used_widget = QtWidgets.QWidget()
        used_widget.setLayout(used_box)
        used_widget.setFixedWidth(self.COLUMN_WIDTHS[4])
        layout.addWidget(used_widget)

        status_box = QtWidgets.QHBoxLayout()
        status_box.setSpacing(6)
        self.status_dot = StatusDot()
        status_box.addWidget(self.status_dot)
        self.status_label = QtWidgets.QLabel("")
        self.status_label.setFont(mono_font(9))
        self.status_label.setObjectName("UniverseCardStatus")
        status_box.addWidget(self.status_label)
        status_widget = QtWidgets.QWidget()
        status_widget.setLayout(status_box)
        status_widget.setFixedWidth(self.COLUMN_WIDTHS[5])
        layout.addWidget(status_widget)

    def update_data(self, universe: Universe, used: int,
                    selected: bool) -> None:
        self.name_label.setText(universe.name or f"Universe {universe.id}")
        protocol = universe.output.get("plugin", "E1.31")
        self.output_chip.setText(protocol.upper())
        self.destination_label.setText(destination_summary(universe))
        self.used_label.setText(f"{used}/512")
        self.channel_bar.set_state(used / 512.0, selected)
        ready = is_ready(universe)
        self.status_dot.set_ok(ready)
        self.status_label.setText("READY" if ready else "UNSET")
        self.set_selected(selected)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.output_chip.setProperty("active",
                                     "true" if selected else "false")
        for widget in (self, self.output_chip):
            style = widget.style()
            if style:
                style.unpolish(widget)
                style.polish(widget)

    def mousePressEvent(self, event):
        self.clicked.emit(self.universe_id)
        event.accept()

    def contextMenuEvent(self, event):
        # Right-click a card: Add / Remove-this-universe menu. Accept the
        # event so it does not also bubble up to the list's own add menu.
        self.context_requested.emit(self.universe_id, event.globalPos())
        event.accept()


class ConfigurationTab(BaseTab):
    """Universe configuration: card list + inspector (North Star 1d)."""

    def __init__(self, config: Configuration, parent=None):
        if not hasattr(config, 'universes'):
            config.universes = {}
            config.initialize_default_universes()
        self._selected_id = None
        self._cards = {}
        super().__init__(config, parent)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def setup_ui(self):
        from gui.typography import DisplayLabel, MicroLabel, display_font

        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 38px action strip matching the Fixtures tab, so the accent
        # "+ ADD ..." button lands in the exact same spot when switching
        # between the two tabs. No tab title: the shell subnav names the
        # screen (reference 03).
        strip = QtWidgets.QWidget()
        strip.setFixedHeight(38)
        strip_row = QtWidgets.QHBoxLayout(strip)
        strip_row.setContentsMargins(16, 0, 16, 0)
        strip_row.setSpacing(12)
        strip_row.addStretch(1)

        # No manual "UPDATE CONFIG" button: inspector edits write through
        # live, and unsaved changes are autosaved for crash recovery, so
        # there is nothing to push by hand. Ctrl+S writes the project file.
        self.add_universe_btn = QtWidgets.QPushButton("+ ADD UNIVERSE")
        self.add_universe_btn.setProperty("role", "cta-accent")
        self.add_universe_btn.setFont(display_font(11, QFont.Weight.Bold,
                                                   tracking_em=0.08))
        self.add_universe_btn.setToolTip("Add Universe")
        self.add_universe_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        strip_row.addWidget(self.add_universe_btn)
        main_layout.addWidget(strip)

        # Body + status strip carry the tab's inner margins.
        content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(content)
        content_layout.setContentsMargins(16, 10, 16, 12)
        content_layout.setSpacing(10)

        body = QtWidgets.QHBoxLayout()
        body.setSpacing(16)

        # -- Left: mono header + card list ------------------------------
        list_column = QtWidgets.QVBoxLayout()
        list_column.setSpacing(0)

        header_row = QtWidgets.QHBoxLayout()
        header_row.setContentsMargins(16, 0, 16, 8)
        header_row.setSpacing(12)
        widths = UniverseRowCard.COLUMN_WIDTHS
        for text, width in (("UNI", widths[0]), ("NAME", widths[1]),
                            ("OUTPUT", widths[2]), ("DESTINATION", -1),
                            ("CHANNELS USED", widths[4]),
                            ("STATUS", widths[5])):
            label = MicroLabel(text, point_size=8, tracking_em=0.1)
            if width > 0:
                label.setFixedWidth(width)
                header_row.addWidget(label)
            else:
                header_row.addWidget(label, 1)
        list_column.addLayout(header_row)

        self.card_container = QtWidgets.QVBoxLayout()
        self.card_container.setSpacing(0)
        cards_host = QtWidgets.QWidget()
        # Right-click empty list space to add a universe (cards handle
        # their own right-click for the per-card menu).
        self.card_list_host = cards_host
        cards_host.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        cards_host.customContextMenuRequested.connect(
            self._show_list_context_menu)
        cards_layout = QtWidgets.QVBoxLayout(cards_host)
        cards_layout.setContentsMargins(0, 0, 0, 0)
        cards_layout.addLayout(self.card_container)
        cards_layout.addStretch(1)
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(cards_host)
        list_column.addWidget(scroll, 1)

        body.addLayout(list_column, 1)

        # -- Right: inspector -------------------------------------------
        body.addWidget(self._build_inspector())
        content_layout.addLayout(body, 1)
        content_layout.addWidget(self._build_status_strip())
        main_layout.addWidget(content, 1)

        self.update_from_config()

    def _build_inspector(self) -> QtWidgets.QWidget:
        from gui.typography import (
            DisplayLabel, MicroLabel, display_font, mono_font,
        )

        panel = QtWidgets.QWidget()
        panel.setObjectName("UniverseInspector")
        panel.setProperty("role", "inspector")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        panel.setFixedWidth(INSPECTOR_WIDTH)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Reference: display-caps "U1 · MAIN RIG" heading.
        self.inspector_title = DisplayLabel("Universe", point_size=13,
                                            weight=QFont.Weight.Bold,
                                            tracking_em=0.05)
        layout.addWidget(self.inspector_title)

        layout.addWidget(MicroLabel("Name", point_size=8, tracking_em=0.1))
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.textEdited.connect(self._on_name_edited)
        layout.addWidget(self.name_edit)

        layout.addWidget(MicroLabel("Output type", point_size=8,
                                    tracking_em=0.1))
        chips_row = QtWidgets.QHBoxLayout()
        chips_row.setSpacing(4)
        self.protocol_buttons = {}
        group = QtWidgets.QButtonGroup(panel)
        group.setExclusive(True)
        for protocol in PROTOCOLS:
            button = QtWidgets.QPushButton(protocol.upper())
            button.setCheckable(True)
            button.setProperty("role", "output-select")
            button.setFont(mono_font(8, tracking_em=0.05))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _=False, p=protocol: self._on_protocol_selected(p))
            group.addButton(button)
            chips_row.addWidget(button)
            self.protocol_buttons[protocol] = button
        layout.addLayout(chips_row)

        # Per-protocol parameter pages
        self.param_stack = QtWidgets.QStackedWidget()

        # ArtNet page
        artnet_page = QtWidgets.QWidget()
        artnet_form = QtWidgets.QFormLayout(artnet_page)
        artnet_form.setContentsMargins(0, 4, 0, 0)
        self.artnet_ip = QtWidgets.QLineEdit()
        self.artnet_subnet = QtWidgets.QLineEdit()
        self.artnet_universe = QtWidgets.QLineEdit()
        artnet_form.addRow("Target IP", self.artnet_ip)
        artnet_form.addRow("Net", self.artnet_subnet)
        artnet_form.addRow("Universe (0-based)", self.artnet_universe)
        # Output rate is a real constant of the ArtNet sender, not a
        # setting: show it as a read-only readout (reference RATE cell).
        from utils.artnet.sender import ArtNetSender
        self.artnet_rate = QtWidgets.QLabel(
            f"{ArtNetSender.MAX_SEND_RATE_HZ} Hz")
        self.artnet_rate.setFont(mono_font(9))
        self.artnet_rate.setToolTip(
            "ArtNet output is rate limited to "
            f"{ArtNetSender.MAX_SEND_RATE_HZ} Hz (fixed).")
        artnet_form.addRow("Rate", self.artnet_rate)
        # "Broadcast" is the 255.255.255.255 target convention, not a
        # separate model field: the toggle just drives the IP.
        self.artnet_broadcast = QtWidgets.QCheckBox("Broadcast")
        self.artnet_broadcast.setToolTip(
            "Send to 255.255.255.255 so every node on the subnet "
            "receives the universe.")
        self.artnet_broadcast.toggled.connect(self._on_broadcast_toggled)
        artnet_form.addRow("", self.artnet_broadcast)
        for edit, key in ((self.artnet_ip, "ip"),
                          (self.artnet_subnet, "subnet"),
                          (self.artnet_universe, "universe")):
            edit.textEdited.connect(
                lambda text, k=key: self._on_param_edited(k, text))
        self.artnet_ip.textEdited.connect(
            lambda _: self._sync_broadcast_checkbox())
        self.param_stack.addWidget(artnet_page)

        # E1.31 page
        e131_page = QtWidgets.QWidget()
        e131_form = QtWidgets.QFormLayout(e131_page)
        e131_form.setContentsMargins(0, 4, 0, 0)
        self.e131_multicast = QtWidgets.QCheckBox("Multicast")
        self.e131_multicast.setToolTip(
            "E1.31 Multicast mode\n"
            "Checked: uses multicast IP (auto-calculated from universe)\n"
            "Unchecked: uses unicast IP (manual entry)")
        self.e131_multicast.toggled.connect(self._on_multicast_toggled)
        e131_form.addRow("", self.e131_multicast)
        self.e131_ip = QtWidgets.QLineEdit()
        self.e131_port = QtWidgets.QLineEdit()
        self.e131_universe = QtWidgets.QLineEdit()
        e131_form.addRow("IP address", self.e131_ip)
        e131_form.addRow("Port", self.e131_port)
        e131_form.addRow("Universe", self.e131_universe)
        self.e131_ip.textEdited.connect(
            lambda text: self._on_param_edited("ip", text))
        self.e131_port.textEdited.connect(
            lambda text: self._on_param_edited("port", text))
        self.e131_universe.textEdited.connect(self._on_e131_universe_edited)
        self.param_stack.addWidget(e131_page)

        # DMX USB page
        usb_page = QtWidgets.QWidget()
        usb_form = QtWidgets.QVBoxLayout(usb_page)
        usb_form.setContentsMargins(0, 4, 0, 0)
        self.device_combo = QtWidgets.QComboBox()
        self.device_combo.addItems(get_device_display_names())
        self.device_combo.currentTextChanged.connect(self._on_device_changed)
        usb_form.addWidget(self.device_combo)
        self.refresh_devices_btn = QtWidgets.QPushButton("Refresh Devices")
        self.refresh_devices_btn.setToolTip("Refresh USB DMX device list")
        usb_form.addWidget(self.refresh_devices_btn)
        usb_form.addStretch(1)
        self.param_stack.addWidget(usb_page)

        layout.addWidget(self.param_stack)

        # Info explainer (reference: info-blue left bar). Only meaningful
        # for ArtNet's 0-based numbering, so it hides on other protocols.
        self.numbering_hint = QtWidgets.QLabel(
            "ArtNet universe numbering is 0-based to match the wire "
            "protocol. QLC+ shows this universe as \"1\".")
        self.numbering_hint.setProperty("role", "hint-info")
        self.numbering_hint.setWordWrap(True)
        hint_font = self.numbering_hint.font()
        hint_font.setPointSize(8)
        self.numbering_hint.setFont(hint_font)
        layout.addWidget(self.numbering_hint)

        layout.addStretch(1)

        self.remove_universe_btn = QtWidgets.QPushButton("Remove Universe")
        self.remove_universe_btn.setProperty("role", "destructive")
        layout.addWidget(self.remove_universe_btn)

        self._page_for = {"ArtNet": 0, "E1.31": 1, "DMX USB": 2}
        return panel

    def _build_status_strip(self) -> QtWidgets.QWidget:
        """Mono footer: universe count + how many have a destination."""
        from gui.typography import MicroLabel

        strip = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        self.status_line = MicroLabel("", point_size=8, tracking_em=0.1)
        row.addWidget(self.status_line)
        row.addStretch(1)
        return strip

    def _refresh_status_strip(self) -> None:
        universes = getattr(self.config, "universes", {}) or {}
        ready = sum(1 for u in universes.values() if is_ready(u))
        total = len(universes)
        noun = "UNIVERSE" if total == 1 else "UNIVERSES"
        self.status_line.setText(f"{total} {noun} · {ready} CONFIGURED")

    def connect_signals(self):
        self.add_universe_btn.clicked.connect(self._add_universe)
        self.remove_universe_btn.clicked.connect(self._remove_universe)
        self.refresh_devices_btn.clicked.connect(self._refresh_devices)

    # ------------------------------------------------------------------
    # Config <-> UI
    # ------------------------------------------------------------------
    def update_from_config(self):
        """Rebuild the card list from the configuration."""
        while self.card_container.count():
            item = self.card_container.takeAt(0)
            widget = item.widget()
            if widget:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._cards = {}

        universes = getattr(self.config, "universes", {}) or {}
        if self._selected_id not in universes:
            self._selected_id = min(universes) if universes else None

        for universe_id, universe in sorted(universes.items()):
            card = UniverseRowCard(universe_id)
            card.clicked.connect(self._on_card_clicked)
            card.context_requested.connect(self._show_card_context_menu)
            self.card_container.addWidget(card)
            self._cards[universe_id] = card
        self._refresh_cards()
        self._load_inspector()

    def _refresh_cards(self):
        for universe_id, card in self._cards.items():
            universe = self.config.universes.get(universe_id)
            if universe is None:
                continue
            card.update_data(universe, channels_used(self.config, universe_id),
                             universe_id == self._selected_id)
        if hasattr(self, "status_line"):
            self._refresh_status_strip()

    def _selected_universe(self):
        if self._selected_id is None:
            return None
        return self.config.universes.get(self._selected_id)

    def _load_inspector(self):
        universe = self._selected_universe()
        enabled = universe is not None
        for widget in (self.name_edit, self.remove_universe_btn,
                       self.param_stack):
            widget.setEnabled(enabled)
        for button in self.protocol_buttons.values():
            button.setEnabled(enabled)
        if universe is None:
            self.inspector_title.setText("No universe")
            self.name_edit.setText("")
            self.numbering_hint.setVisible(False)
            return

        # Reference heading: "U1 · MAIN RIG".
        name = universe.name or f"Universe {universe.id}"
        self.inspector_title.setText(f"U{universe.id} · {name}")
        protocol = universe.output.get("plugin", "E1.31")
        params = universe.output.get("parameters", {}) or {}

        self.name_edit.blockSignals(True)
        self.name_edit.setText(universe.name or f"Universe {universe.id}")
        self.name_edit.blockSignals(False)

        for name, button in self.protocol_buttons.items():
            button.blockSignals(True)
            button.setChecked(name == protocol)
            button.blockSignals(False)
        self.param_stack.setCurrentIndex(self._page_for.get(protocol, 1))

        # The 0-based-numbering explainer only applies to ArtNet.
        self.numbering_hint.setVisible(protocol == "ArtNet")

        if protocol == "ArtNet":
            self._set_text_silent(self.artnet_ip, params.get("ip", ""))
            self._set_text_silent(self.artnet_subnet, params.get("subnet", "0"))
            self._set_text_silent(self.artnet_universe,
                                  params.get("universe", "0"))
            self._sync_broadcast_checkbox()
            self.artnet_ip.setEnabled(not self.artnet_broadcast.isChecked())
        elif protocol == "E1.31":
            multicast = (params.get("multicast", "true") or
                         "true").lower() == "true"
            self.e131_multicast.blockSignals(True)
            self.e131_multicast.setChecked(multicast)
            self.e131_multicast.blockSignals(False)
            self._set_text_silent(self.e131_ip, params.get("ip", ""))
            self.e131_ip.setEnabled(not multicast)
            self._set_text_silent(self.e131_port, params.get("port", "5568"))
            self._set_text_silent(self.e131_universe,
                                  params.get("universe", "1"))
        else:  # DMX USB
            stored = params.get("device", "")
            self.device_combo.blockSignals(True)
            index = -1
            for i in range(self.device_combo.count()):
                if stored and stored in self.device_combo.itemText(i):
                    index = i
                    break
            if index >= 0:
                self.device_combo.setCurrentIndex(index)
            self.device_combo.blockSignals(False)

    @staticmethod
    def _set_text_silent(edit: QtWidgets.QLineEdit, text: str) -> None:
        edit.blockSignals(True)
        edit.setText(text)
        edit.blockSignals(False)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def _on_card_clicked(self, universe_id: int):
        self._selected_id = universe_id
        self._refresh_cards()
        self._load_inspector()

    def _on_name_edited(self, text: str):
        universe = self._selected_universe()
        if universe is not None:
            universe.name = text
            self.inspector_title.setText(f"U{universe.id} · {text}")
            self._refresh_cards()

    def _on_protocol_selected(self, protocol: str):
        universe = self._selected_universe()
        if universe is None:
            return
        if universe.output.get("plugin") != protocol:
            universe.output["plugin"] = protocol
            params = universe.output.setdefault("parameters", {})
            params.clear()
            params.update(_PROTOCOL_DEFAULTS[protocol])
        self._load_inspector()
        self._refresh_cards()

    def _on_param_edited(self, key: str, text: str):
        universe = self._selected_universe()
        if universe is not None:
            universe.output.setdefault("parameters", {})[key] = text
            self._refresh_cards()

    def _on_e131_universe_edited(self, text: str):
        universe = self._selected_universe()
        if universe is None:
            return
        params = universe.output.setdefault("parameters", {})
        params["universe"] = text
        if (params.get("multicast", "true") or "true").lower() == "true":
            try:
                number = int(text) if text else 1
            except ValueError:
                number = 1
            params["ip"] = f"239.255.{number >> 8}.{number & 0xFF}"
            self._set_text_silent(self.e131_ip, params["ip"])
        self._refresh_cards()

    def _on_broadcast_toggled(self, checked: bool):
        """Broadcast is the 255.255.255.255 target, not a model flag."""
        universe = self._selected_universe()
        if universe is None:
            return
        params = universe.output.setdefault("parameters", {})
        if checked:
            self._previous_unicast_ip = params.get("ip", "")
            params["ip"] = BROADCAST_IP
        elif params.get("ip") == BROADCAST_IP:
            params["ip"] = getattr(self, "_previous_unicast_ip", "") or ""
        self._set_text_silent(self.artnet_ip, params.get("ip", ""))
        self.artnet_ip.setEnabled(not checked)
        self._refresh_cards()

    def _sync_broadcast_checkbox(self):
        """Keep the toggle honest when the IP is typed by hand."""
        is_broadcast = self.artnet_ip.text().strip() == BROADCAST_IP
        self.artnet_broadcast.blockSignals(True)
        self.artnet_broadcast.setChecked(is_broadcast)
        self.artnet_broadcast.blockSignals(False)

    def _on_multicast_toggled(self, checked: bool):
        universe = self._selected_universe()
        if universe is None:
            return
        params = universe.output.setdefault("parameters", {})
        params["multicast"] = str(checked).lower()
        if checked:
            try:
                number = int(params.get("universe", "1") or 1)
            except ValueError:
                number = 1
            params["ip"] = f"239.255.{number >> 8}.{number & 0xFF}"
            self._set_text_silent(self.e131_ip, params["ip"])
        self.e131_ip.setEnabled(not checked)
        self._refresh_cards()

    def _on_device_changed(self, display_name: str):
        universe = self._selected_universe()
        if universe is None:
            return
        port = get_device_port_by_display_name(display_name)
        universe.output.setdefault("parameters", {})["device"] = (
            port if port else display_name)
        self._refresh_cards()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def save_to_config(self):
        """Inspector edits write through immediately; this is kept for
        the gui.py save flow and just refreshes derived displays."""
        self._refresh_cards()
        print("Universe configuration updated")

    def _add_universe(self):
        existing = list(self.config.universes.keys()) or [0]
        universe_id = max(existing) + 1
        self.config.universes[universe_id] = Universe(
            id=universe_id,
            name=f"Universe {universe_id}",
            output={
                'plugin': 'E1.31',
                'line': '0',
                'parameters': {
                    'multicast': 'true',
                    'ip': f'239.255.0.{universe_id}',
                    'port': '5568',
                    'universe': str(universe_id),
                },
            },
        )
        self._selected_id = universe_id
        self.update_from_config()

    def _remove_universe(self):
        """The inspector's Remove button: drops the selected universe."""
        self._remove_universe_by_id(self._selected_id)

    def _remove_universe_by_id(self, universe_id):
        """Drop one universe by id (shared by the button and the
        right-click menu). No-op when it is missing/None."""
        if universe_id is None or universe_id not in self.config.universes:
            return
        self.config.universes.pop(universe_id, None)
        if self._selected_id == universe_id:
            self._selected_id = None
        self.update_from_config()

    # ------------------------------------------------------------------
    # Right-click context menus (add / remove)
    # ------------------------------------------------------------------
    def _show_card_context_menu(self, universe_id: int,
                                global_pos: QtCore.QPoint):
        """Menu for a right-clicked card: select it, then offer Add and
        Remove-this-universe."""
        self._on_card_clicked(universe_id)
        self._exec_universe_menu(global_pos, universe_id)

    def _show_list_context_menu(self, pos: QtCore.QPoint):
        """Menu for empty list space: Add only (nothing to remove)."""
        global_pos = self.card_list_host.mapToGlobal(pos)
        self._exec_universe_menu(global_pos, None)

    def _exec_universe_menu(self, global_pos: QtCore.QPoint, universe_id):
        menu = QtWidgets.QMenu(self)
        menu.addAction("Add Universe", self._add_universe)
        if universe_id is not None:
            menu.addAction(
                "Remove Universe",
                lambda: self._remove_universe_by_id(universe_id))
        menu.exec(global_pos)

    def _refresh_devices(self):
        names = get_device_display_names()
        current = self.device_combo.currentText()
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        self.device_combo.addItems(names)
        index = self.device_combo.findText(current)
        if index >= 0:
            self.device_combo.setCurrentIndex(index)
        self.device_combo.blockSignals(False)
        print("USB DMX device list refreshed")
