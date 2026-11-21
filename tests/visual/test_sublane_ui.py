# test_sublane_ui.py
# Visual test for sublane rendering

import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt6.QtCore import Qt

from config.models import (
    Configuration, Fixture, FixtureMode, FixtureGroup,
    LightLane
)
from timeline_ui.light_lane_widget import LightLaneWidget


class SublaneTestWindow(QMainWindow):
    """Test window to visualize sublane rendering."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Sublane Rendering Test")
        self.setGeometry(100, 100, 1200, 900)  # Increased height to fit all lanes

        # Create test configuration
        self.config = self.create_test_config()

        # Setup UI
        self.setup_ui()

    def create_test_config(self):
        """Create a test configuration with different fixture types."""
        config = Configuration()

        # Test Fixture 1: Moving Head (should show 4 sublanes)
        moving_head = Fixture(
            universe=1,
            address=1,
            manufacturer="Varytec",
            model="Hero Spot 60",
            name="MH1",
            group="Moving Heads",
            direction="",
            current_mode="14-Channel",
            available_modes=[FixtureMode("14-Channel", 14)],
            type="MH"
        )

        # Test Fixture 2: RGBW Par (should show 2 sublanes: Dimmer, Colour)
        rgbw_par = Fixture(
            universe=1,
            address=20,
            manufacturer="Stairville",
            model="Retro Flat Par 18x12W RGBW ",
            name="Par1",
            group="RGBW Pars",
            direction="",
            current_mode="8-Channel",
            available_modes=[FixtureMode("8-Channel", 8)],
            type="WASH"
        )

        # Test Fixture 3: Simple dimmer (would show 1 sublane if we had one)
        # For now, we'll use another RGBW as placeholder
        simple_fixture = Fixture(
            universe=1,
            address=30,
            manufacturer="Generic",
            model="Dimmer",
            name="Dimmer1",
            group="Dimmers",
            direction="",
            current_mode="1-Channel",
            available_modes=[FixtureMode("1-Channel", 1)],
            type="PAR"
        )

        # Create groups
        config.groups["Moving Heads"] = FixtureGroup(
            name="Moving Heads",
            fixtures=[moving_head]
        )

        config.groups["RGBW Pars"] = FixtureGroup(
            name="RGBW Pars",
            fixtures=[rgbw_par]
        )

        config.groups["Dimmers"] = FixtureGroup(
            name="Dimmers",
            fixtures=[simple_fixture]
        )

        return config

    def setup_ui(self):
        """Setup the test UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setSpacing(20)

        # Title
        title = QLabel("Sublane Rendering Test")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: white; background-color: #333; padding: 10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Test 1: Moving Head Lane (4 sublanes)
        self.add_test_lane(
            layout,
            "Test 1: Moving Head (Expected: 4 sublanes - Dimmer, Colour, Movement, Special)",
            "Moving Heads"
        )

        # Test 2: RGBW Par Lane (2 sublanes)
        self.add_test_lane(
            layout,
            "Test 2: RGBW Par (Expected: 2 sublanes - Dimmer, Colour)",
            "RGBW Pars"
        )

        # Test 3: Simple Dimmer Lane (1 sublane - using placeholder for now)
        self.add_test_lane(
            layout,
            "Test 3: Simple Fixture (Expected: varies based on fixture definition)",
            "Dimmers"
        )

        layout.addStretch()

    def add_test_lane(self, layout, description, group_name):
        """Add a test lane to the layout."""
        # Description label
        desc_label = QLabel(description)
        desc_label.setStyleSheet("font-size: 12px; color: #666; padding: 5px;")
        layout.addWidget(desc_label)

        # Create a light lane
        lane = LightLane(
            name=f"{group_name} Lane",
            fixture_targets=[group_name]
        )

        # Create the lane widget with config
        lane_widget = LightLaneWidget(
            lane=lane,
            fixture_groups=list(self.config.groups.keys()),
            parent=self,
            config=self.config
        )

        layout.addWidget(lane_widget)

        # Info label showing detected capabilities
        if group_name in self.config.groups:
            group = self.config.groups[group_name]
            if group.capabilities:
                caps = group.capabilities
                cap_info = f"Detected: {lane_widget.num_sublanes} sublanes | "
                cap_info += f"Dimmer: {caps.has_dimmer}, "
                cap_info += f"Colour: {caps.has_colour}, "
                cap_info += f"Movement: {caps.has_movement}, "
                cap_info += f"Special: {caps.has_special}"

                info_label = QLabel(cap_info)
                info_label.setStyleSheet("font-size: 10px; color: #999; padding: 2px 5px; font-family: monospace;")
                layout.addWidget(info_label)


def main():
    """Run the sublane rendering test."""
    app = QApplication(sys.argv)

    # Set dark theme
    app.setStyleSheet("""
        QMainWindow {
            background-color: #1e1e1e;
        }
        QWidget {
            background-color: #1e1e1e;
            color: white;
        }
    """)

    window = SublaneTestWindow()
    window.show()

    print("=" * 60)
    print("Sublane Rendering Test")
    print("=" * 60)
    print("\nThis test visualizes the sublane rendering:")
    print("- Each lane should show horizontal dashed lines separating sublanes")
    print("- Lane height should vary based on number of sublanes (60px each)")
    print("- Moving Head: 4 sublanes (240px)")
    print("- RGBW Par: 2 sublanes (120px)")
    print("\nClose the window to exit the test.")
    print("=" * 60)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
