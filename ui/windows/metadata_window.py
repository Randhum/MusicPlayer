"""Metadata display window."""

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk

from ui.components.metadata_panel import MetadataPanel
from core.metadata import TrackMetadata


class MetadataWindow(Gtk.ApplicationWindow):
    """Window for displaying track metadata."""
    
    def __init__(self, app, application):
        super().__init__(application=app)
        self.application = application
        self.set_title("Now Playing")
        self.set_default_size(300, 500)
        
        # Create UI
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_child(main_box)
        
        # Metadata panel component
        self.metadata_panel = MetadataPanel()
        main_box.append(self.metadata_panel)
    
    def set_track(self, track: TrackMetadata):
        """Set the track to display."""
        self.metadata_panel.set_track(track)

