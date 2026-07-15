# gui/tabs/base_tab.py

from PyQt6 import QtCore, QtWidgets
from config.models import Configuration


class BaseTab(QtWidgets.QWidget):
    """Base class for all tab components

    Provides common interface for tab lifecycle and configuration management.
    Follows the pattern established by StageView.
    """

    def __init__(self, config: Configuration, parent=None):
        """Initialize base tab

        Args:
            config: Shared Configuration object
            parent: Parent widget (typically MainWindow)
        """
        super().__init__(parent)
        # Themed page background. A bare QWidget page falls back to the
        # platform palette (light gray) because the app QSS only sets
        # `color` on QWidget - this is why tab contents looked light in
        # a dark app. role="tab-page" is painted $window$-dark by the
        # theme template; WA_StyledBackground makes plain QWidgets
        # honor it.
        self.setProperty("role", "tab-page")
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_StyledBackground, True)
        self.config = config
        self.setup_ui()
        self.connect_signals()

    def setup_ui(self):
        """Set up UI components

        Override this method to build the tab's user interface.
        """
        raise NotImplementedError("Subclasses must implement setup_ui()")

    def connect_signals(self):
        """Connect internal signals

        Override this method to connect widget signals to handlers.
        Optional - some tabs may not need signal connections.
        """
        pass

    def update_from_config(self):
        """Refresh UI from configuration changes

        Override this method to update the UI when the shared
        configuration has been modified by another component.
        """
        pass

    def save_to_config(self):
        """Persist UI changes to configuration

        Override this method to save the current UI state
        back to the shared configuration object.
        """
        pass

    def on_tab_activated(self):
        """Called when tab becomes visible

        Override to perform actions when the user switches to this tab.
        Default behavior is to refresh from config.
        """
        self.update_from_config()

    def on_tab_deactivated(self):
        """Called when leaving tab

        Override to perform cleanup or auto-save when user switches away.
        Default behavior is to save changes to config.
        """
        self.save_to_config()

    def show_error(self, title: str, message: str):
        """Show error dialog with consistent styling

        Args:
            title: Dialog title
            message: Error message to display
        """
        QtWidgets.QMessageBox.critical(self, title, message)

    def show_info(self, title: str, message: str):
        """Show information dialog with consistent styling

        Args:
            title: Dialog title
            message: Information message to display
        """
        QtWidgets.QMessageBox.information(self, title, message)

    def validate_config(self) -> bool:
        """Validate configuration before save

        Override to add tab-specific validation logic.

        Returns:
            True if configuration is valid, False otherwise
        """
        return True
