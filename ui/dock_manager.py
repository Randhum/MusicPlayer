"""Dock manager for modular dockable panels."""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
import json
from pathlib import Path
from typing import Callable, Dict, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("GLib", "2.0")
gi.require_version("Gtk", "4.0")
from gi.repository import GLib, Gtk

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.config import get_config
from core.logging import get_logger

logger = get_logger(__name__)


# Default detached window size
DEFAULT_DETACHED_WIDTH = 400
DEFAULT_DETACHED_HEIGHT = 500


class DockablePanel(Gtk.Box):
    """A panel that can be docked or detached as a separate window."""

    def __init__(
        self, title: str, content: Gtk.Widget, icon_name: str = "view-list-symbolic"
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.title = title
        self.content = content
        self.icon_name = icon_name
        self.is_detached = False
        self.detached_window: Optional[Gtk.Window] = None
        self.parent_container = None
        self.parent_position = None  # 'start' or 'end' for Paned
        self.on_reattach: Optional[Callable] = None

        # Create header bar with title and detach button
        self.header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
        self.header.add_css_class("dock-header")
        self.header.set_margin_start(5)
        self.header.set_margin_end(5)
        self.header.set_margin_top(3)
        self.header.set_margin_bottom(3)

        # Title label
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("title-3")
        title_label.set_hexpand(True)
        title_label.set_halign(Gtk.Align.START)
        self.header.append(title_label)

        # Detach button
        self.detach_button = Gtk.Button()
        self.detach_button.set_icon_name("window-new-symbolic")
        self.detach_button.set_tooltip_text("Detach panel")
        self.detach_button.add_css_class("flat")
        self.detach_button.connect("clicked", self._on_detach_clicked)
        self.header.append(self.detach_button)

        self.append(self.header)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))

        # Content container
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_box.set_vexpand(True)
        self.content_box.set_hexpand(True)
        self.content_box.append(content)
        self.append(self.content_box)

    def _on_detach_clicked(self, button):
        """Handle detach button click."""
        if self.is_detached:
            self._reattach()
        else:
            self._detach()

    def _detach(self):
        """Detach panel as a separate window."""
        if self.is_detached:
            return

        # Remember parent container
        self.parent_container = self.get_parent()

        # Create detached window
        self.detached_window = Gtk.Window(title=self.title)
        self.detached_window.set_default_size(
            DEFAULT_DETACHED_WIDTH, DEFAULT_DETACHED_HEIGHT
        )
        self.detached_window.set_resizable(True)  # Allow resizing and maximizing
        self.detached_window.connect("close-request", self._on_window_close)

        # Remove from parent and add to window
        if self.parent_container:
            # Gtk.Paned does not have remove(); clear the appropriate child
            if isinstance(self.parent_container, Gtk.Paned):
                if self.parent_container.get_start_child() is self:
                    self.parent_position = "start"
                    self.parent_container.set_start_child(None)
                elif self.parent_container.get_end_child() is self:
                    self.parent_position = "end"
                    self.parent_container.set_end_child(None)
            # Gtk.Box and other containers support remove()
            elif isinstance(self.parent_container, Gtk.Box):
                self.parent_container.remove(self)
            elif isinstance(self.parent_container, Gtk.Window):
                self.parent_container.set_child(None)

        self.detached_window.set_child(self)
        self.detached_window.present()

        # Update button
        self.detach_button.set_icon_name("window-restore-symbolic")
        self.detach_button.set_tooltip_text("Reattach panel")
        self.is_detached = True

    def _reattach(self):
        """Reattach panel to main window."""
        if not self.is_detached:
            return

        # Remove from detached window first
        if self.detached_window:
            # Make sure panel is removed from window before destroying
            if self.detached_window.get_child() is self:
                self.detached_window.set_child(None)
            self.detached_window.destroy()
            self.detached_window = None

        # Update button
        self.detach_button.set_icon_name("window-new-symbolic")
        self.detach_button.set_tooltip_text("Detach panel")
        self.is_detached = False

        # Notify dock manager to reattach (this will add panel back to parent)
        if self.on_reattach:
            self.on_reattach(self)

    def _on_window_close(self, window):
        """Handle detached window close."""
        self._reattach()
        return True  # Prevent default close behavior


class DockManager:
    """Manages dockable panels with layout saving/loading."""

    def __init__(self, main_window: Gtk.Window):
        self.main_window = main_window
        self.panels: Dict[str, DockablePanel] = {}
        self.layout_config: Dict = {}
        # Get layout file from config
        config = get_config()
        self.config_path = str(config.layout_file)

    def create_panel(
        self,
        panel_id: str,
        title: str,
        content: Gtk.Widget,
        icon_name: str = "view-list-symbolic",
    ) -> DockablePanel:
        """Create a new dockable panel."""
        panel = DockablePanel(title, content, icon_name)
        # Note: The reattach callback is typically overridden by the main window
        # to call its own _reattach_panel method. This default implementation
        # is a fallback that can be used if main window doesn't override it.
        panel.on_reattach = lambda p: self._on_panel_reattach(panel_id, p)
        self.panels[panel_id] = panel
        return panel

    def _on_panel_reattach(self, panel_id: str, panel: DockablePanel):
        """Handle panel reattachment.

        This is a default implementation that attempts to reattach the panel
        to its original parent container. The main window typically overrides
        this callback to use its own _reattach_panel method which has more
        context about the layout structure.
        """
        if not panel or not panel.parent_container:
            return

        # Remove panel from current parent if any
        current_parent = panel.get_parent()
        if current_parent:
            if isinstance(current_parent, Gtk.Paned):
                if current_parent.get_start_child() is panel:
                    current_parent.set_start_child(None)
                elif current_parent.get_end_child() is panel:
                    current_parent.set_end_child(None)
            elif isinstance(current_parent, Gtk.Box):
                current_parent.remove(panel)
            elif isinstance(current_parent, Gtk.Window):
                current_parent.set_child(None)

        # Reattach to original parent container
        parent = panel.parent_container
        if isinstance(parent, Gtk.Paned):
            # Use stored position or default to end
            if panel.parent_position == "start":
                parent.set_start_child(panel)
            else:
                parent.set_end_child(panel)
        elif isinstance(parent, Gtk.Box):
            parent.append(panel)
        elif isinstance(parent, Gtk.Window):
            parent.set_child(panel)

    def create_paned_layout(
        self,
        *panels: DockablePanel,
        orientation: Gtk.Orientation = Gtk.Orientation.HORIZONTAL
    ) -> Gtk.Paned:
        """Create a paned container with multiple panels."""
        if len(panels) < 2:
            raise ValueError("Need at least 2 panels for a paned layout")

        # Build nested paned structure
        result = Gtk.Paned(orientation=orientation)
        result.set_start_child(panels[0])

        if len(panels) == 2:
            result.set_end_child(panels[1])
        else:
            # Recursively create paned for remaining panels
            remaining = self.create_paned_layout(*panels[1:], orientation=orientation)
            result.set_end_child(remaining)

        result.set_shrink_start_child(False)
        result.set_shrink_end_child(False)
        result.set_resize_start_child(True)
        result.set_resize_end_child(True)

        return result

    def save_layout(self):
        """Save current layout configuration."""
        config = {"panels": {}, "positions": {}}

        for panel_id, panel in self.panels.items():
            config["panels"][panel_id] = {
                "detached": panel.is_detached,
                "visible": panel.get_visible(),
            }

            if panel.is_detached and panel.detached_window:
                # Save detached window position
                width = panel.detached_window.get_width()
                height = panel.detached_window.get_height()
                config["positions"][panel_id] = {"width": width, "height": height}

        try:
            with open(self.config_path, "w") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            logger.error("Failed to save layout: %s", e, exc_info=True)

    def load_layout(self):
        """Load layout configuration."""
        try:
            if Path(self.config_path).exists():
                with open(self.config_path, "r") as f:
                    self.layout_config = json.load(f)

                # Apply configuration
                for panel_id, config in self.layout_config.get("panels", {}).items():
                    if panel_id in self.panels:
                        panel = self.panels[panel_id]
                        if config.get("detached", False):
                            panel._detach()

                            # Apply saved position
                            pos = self.layout_config.get("positions", {}).get(
                                panel_id, {}
                            )
                            if panel.detached_window and pos:
                                panel.detached_window.set_default_size(
                                    pos.get("width", DEFAULT_DETACHED_WIDTH),
                                    pos.get("height", DEFAULT_DETACHED_HEIGHT),
                                )
        except Exception as e:
            logger.error("Failed to load layout: %s", e, exc_info=True)

    def cleanup(self):
        """Clean up all panels and save layout."""
        self.save_layout()

        for panel in self.panels.values():
            if panel.is_detached and panel.detached_window:
                panel.detached_window.destroy()
