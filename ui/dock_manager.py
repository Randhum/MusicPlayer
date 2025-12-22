"""Dock manager for modular dockable panels."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('GLib', '2.0')
from gi.repository import Gtk, GLib, Gio
from typing import Dict, Optional, Callable
import json
import os

from ui.components.fractal_screensaver import FractalBackground


class DockablePanel(Gtk.Box):
    """A panel that can be docked or detached as a separate window."""
    
    def __init__(self, title: str, content: Gtk.Widget, icon_name: str = "view-list-symbolic"):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        
        self.title = title
        self.content = content
        self.icon_name = icon_name
        self.is_detached = False
        self.detached_window: Optional[Gtk.Window] = None
        self.parent_container = None
        self.parent_position = None  # 'start' or 'end' for Paned
        self.on_reattach: Optional[Callable] = None
        self.screensaver_enabled = False
        self.fractal_background: Optional[FractalBackground] = None
        
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
        
        # Screensaver toggle button
        self.screensaver_button = Gtk.Button()
        self.screensaver_button.set_icon_name("applications-graphics-symbolic")
        self.screensaver_button.set_tooltip_text("Toggle fractal screensaver")
        self.screensaver_button.add_css_class("flat")
        self.screensaver_button.connect("clicked", self._on_screensaver_clicked)
        self.header.append(self.screensaver_button)
        
        # Detach button
        self.detach_button = Gtk.Button()
        self.detach_button.set_icon_name("window-new-symbolic")
        self.detach_button.set_tooltip_text("Detach panel")
        self.detach_button.add_css_class("flat")
        self.detach_button.connect("clicked", self._on_detach_clicked)
        self.header.append(self.detach_button)
        
        self.append(self.header)
        self.append(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL))
        
        # Content container (will be replaced with fractal background if enabled)
        self.content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.content_box.set_vexpand(True)
        self.content_box.set_hexpand(True)
        self.content_box.append(content)
        self.append(self.content_box)
    
    def _on_screensaver_clicked(self, button):
        """Handle screensaver toggle button click."""
        self.toggle_screensaver()
    
    def toggle_screensaver(self):
        """Toggle fractal screensaver on/off."""
        if self.screensaver_enabled:
            self._disable_screensaver()
        else:
            self._enable_screensaver()
    
    def _enable_screensaver(self):
        """Enable fractal screensaver background."""
        if self.screensaver_enabled:
            return
        
        # Get content from content_box
        content = None
        child = self.content_box.get_first_child()
        while child:
            if child != self.fractal_background:  # Don't remove fractal background if it exists
                content = child
                self.content_box.remove(child)
                break
            child = child.get_next_sibling()
        
        if not content:
            # Fallback: use original content
            content = self.content
        
        # Create fractal background with content
        self.fractal_background = FractalBackground(
            content=content,
            rules=None,  # Random rules
            iterations=7,  # Reasonable detail level
            color_scheme="binary"
        )
        
        # Replace content_box content
        self.content_box.append(self.fractal_background)
        
        self.screensaver_enabled = True
        self.screensaver_button.set_icon_name("applications-graphics-symbolic")
        self.screensaver_button.set_tooltip_text("Disable fractal screensaver")
    
    def _disable_screensaver(self):
        """Disable fractal screensaver background."""
        if not self.screensaver_enabled:
            return
        
        # Remove fractal background
        if self.fractal_background:
            # Get the original content from the fractal background
            content = self.fractal_background.content_widget
            self.content_box.remove(self.fractal_background)
            self.fractal_background = None
            
            # Restore original content
            if content:
                self.content_box.append(content)
            else:
                # Fallback: use stored content
                if self.content:
                    self.content_box.append(self.content)
        
        self.screensaver_enabled = False
        self.screensaver_button.set_icon_name("applications-graphics-symbolic")
        self.screensaver_button.set_tooltip_text("Enable fractal screensaver")
    
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
        self.detached_window.set_default_size(400, 500)
        self.detached_window.set_resizable(True)  # Allow resizing and maximizing
        self.detached_window.connect("close-request", self._on_window_close)
        
        # Remove from parent and add to window
        if self.parent_container:
            # Gtk.Paned does not have remove(); clear the appropriate child
            if isinstance(self.parent_container, Gtk.Paned):
                if self.parent_container.get_start_child() is self:
                    self.parent_position = 'start'
                    self.parent_container.set_start_child(None)
                elif self.parent_container.get_end_child() is self:
                    self.parent_position = 'end'
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
            # Make sure panel is removed from window before closing
            if self.detached_window.get_child() is self:
                self.detached_window.set_child(None)
            self.detached_window.close()
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
        self.config_path = os.path.expanduser("~/.config/musicplayer/layout.json")
        
        # Ensure config directory exists
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
    
    def create_panel(self, panel_id: str, title: str, content: Gtk.Widget, 
                     icon_name: str = "view-list-symbolic") -> DockablePanel:
        """Create a new dockable panel."""
        panel = DockablePanel(title, content, icon_name)
        panel.on_reattach = lambda p: self._on_panel_reattach(panel_id, p)
        self.panels[panel_id] = panel
        return panel
    
    def _on_panel_reattach(self, panel_id: str, panel: DockablePanel):
        """Handle panel reattachment."""
        # This will be connected to the main window's layout logic
        pass
    
    def create_paned_layout(self, *panels: DockablePanel, 
                           orientation: Gtk.Orientation = Gtk.Orientation.HORIZONTAL) -> Gtk.Paned:
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
        config = {
            "panels": {},
            "positions": {}
        }
        
        for panel_id, panel in self.panels.items():
            config["panels"][panel_id] = {
                "detached": panel.is_detached,
                "visible": panel.get_visible()
            }
            
            if panel.is_detached and panel.detached_window:
                # Save detached window position
                width = panel.detached_window.get_width()
                height = panel.detached_window.get_height()
                config["positions"][panel_id] = {
                    "width": width,
                    "height": height
                }
        
        try:
            with open(self.config_path, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Failed to save layout: {e}")
    
    def load_layout(self):
        """Load layout configuration."""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r') as f:
                    self.layout_config = json.load(f)
                    
                # Apply configuration
                for panel_id, config in self.layout_config.get("panels", {}).items():
                    if panel_id in self.panels:
                        panel = self.panels[panel_id]
                        if config.get("detached", False):
                            panel._detach()
                            
                            # Apply saved position
                            pos = self.layout_config.get("positions", {}).get(panel_id, {})
                            if panel.detached_window and pos:
                                panel.detached_window.set_default_size(
                                    pos.get("width", 400),
                                    pos.get("height", 500)
                                )
        except Exception as e:
            print(f"Failed to load layout: {e}")
    
    def cleanup(self):
        """Clean up all panels and save layout."""
        self.save_layout()
        
        for panel in self.panels.values():
            if panel.is_detached and panel.detached_window:
                panel.detached_window.close()


