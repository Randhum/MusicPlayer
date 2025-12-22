"""Fractal screensaver component with inverted text support."""

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gtk, Gdk, GLib
from typing import Optional, List
import random
import math

# Note: Cairo context is provided by GTK4's draw function, no import needed

from core.fractal_generator import FractalGenerator


class FractalScreensaver(Gtk.DrawingArea):
    """A drawing area that displays a fractal pattern as a screensaver background."""
    
    def __init__(self, rules: Optional[List[int]] = None, iterations: int = 8,
                 color_scheme: str = "binary", animation_speed: float = 0.0):
        """
        Initialize the fractal screensaver.
        
        Args:
            rules: List of 4 rule values (0-15). If None, uses random rules.
            iterations: Number of iterations (determines detail level)
            color_scheme: "binary" (black/white), "grey" (grayscale), or "rgb" (colored)
            animation_speed: Speed of animation (0.0 = static, >0 = animated)
        """
        super().__init__()
        
        # Generate random rules if not provided
        if rules is None:
            rules = [random.randint(0, 15) for _ in range(4)]
        
        self.generator = FractalGenerator(rules=rules, iterations=iterations)
        self.color_scheme = color_scheme
        self.animation_speed = animation_speed
        self.animation_offset = 0.0
        
        # Connect draw signal
        self.set_draw_func(self._on_draw)
        
        # Setup animation timer if needed
        if animation_speed > 0:
            GLib.timeout_add(50, self._animate)  # Update every 50ms
    
    def _on_draw(self, widget, cr, width: int, height: int):
        """Draw the fractal pattern."""
        # Clear background
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        
        # Get fractal data
        fractal = self.generator.generate()
        fractal_size = len(fractal)
        
        # Calculate pixel size
        pixel_width = width / fractal_size
        pixel_height = height / fractal_size
        
        # Draw fractal
        for y in range(fractal_size):
            for x in range(fractal_size):
                value = fractal[y][x]
                
                # Calculate position
                px = x * pixel_width
                py = y * pixel_height
                
                # Set color based on scheme
                if self.color_scheme == "binary":
                    # Black and white
                    color = 1.0 if value == 1 else 0.0
                    cr.set_source_rgb(color, color, color)
                elif self.color_scheme == "grey":
                    # Grayscale with variation
                    base = 1.0 if value == 1 else 0.0
                    # Add slight variation based on position
                    variation = math.sin((x + y) * 0.1 + self.animation_offset) * 0.1
                    color = max(0.0, min(1.0, base + variation))
                    cr.set_source_rgb(color, color, color)
                elif self.color_scheme == "rgb":
                    # Color based on position
                    if value == 1:
                        r = (x / fractal_size + self.animation_offset * 0.1) % 1.0
                        g = (y / fractal_size + self.animation_offset * 0.15) % 1.0
                        b = ((x + y) / (fractal_size * 2) + self.animation_offset * 0.2) % 1.0
                        cr.set_source_rgb(r, g, b)
                    else:
                        cr.set_source_rgb(0, 0, 0)
                else:
                    # Default to binary
                    color = 1.0 if value == 1 else 0.0
                    cr.set_source_rgb(color, color, color)
                
                # Draw rectangle
                cr.rectangle(px, py, pixel_width, pixel_height)
                cr.fill()
        
        return True
    
    def _animate(self):
        """Animation callback."""
        if self.animation_speed > 0:
            self.animation_offset += self.animation_speed
            self.queue_draw()
            return True
        return False
    
    def get_pixel_value(self, x: int, y: int) -> float:
        """
        Get the pixel value (0.0 to 1.0) at a specific position.
        Used for determining text color inversion.
        
        Args:
            x: X coordinate
            y: Y coordinate
        
        Returns:
            Brightness value (0.0 = black, 1.0 = white)
        """
        width = self.get_width()
        height = self.get_height()
        
        if width <= 0 or height <= 0:
            return 0.5  # Default to medium gray
        
        pixel_value = self.generator.get_pixel(x, y, width, height)
        return float(pixel_value)
    
    def regenerate(self, rules: Optional[List[int]] = None):
        """Regenerate the fractal with new rules."""
        if rules is None:
            rules = [random.randint(0, 15) for _ in range(4)]
        
        self.generator = FractalGenerator(rules=rules, iterations=self.generator.iterations)
        self.generator.clear_cache()
        self.queue_draw()


class FractalBackground(Gtk.Box):
    """A container that displays content on a fractal background with inverted text."""
    
    def __init__(self, content: Gtk.Widget, rules: Optional[List[int]] = None,
                 iterations: int = 8, color_scheme: str = "binary"):
        """
        Initialize fractal background container.
        
        Args:
            content: Widget to display on top of fractal
            rules: Fractal rules (None for random)
            iterations: Fractal iterations
            color_scheme: Color scheme for fractal
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        
        # Create overlay to stack screensaver and content
        overlay = Gtk.Overlay()
        
        # Create screensaver as background
        self.screensaver = FractalScreensaver(
            rules=rules,
            iterations=iterations,
            color_scheme=color_scheme,
            animation_speed=0.0  # Static for background
        )
        self.screensaver.set_vexpand(True)
        self.screensaver.set_hexpand(True)
        
        # Add screensaver as base child
        overlay.set_child(self.screensaver)
        
        # Add content as overlay
        self.content_widget = content
        overlay.add_overlay(content)
        
        # Invert widget colors
        self._invert_widget_colors(content)
        
        # Add overlay to box
        self.append(overlay)
        self.set_vexpand(True)
        self.set_hexpand(True)
    
    def _invert_widget_colors(self, widget: Gtk.Widget):
        """Recursively invert text colors in widgets based on background."""
        # Add CSS class for inverted text
        if isinstance(widget, Gtk.Label):
            widget.add_css_class("fractal-inverted-text")
        elif isinstance(widget, Gtk.Button):
            widget.add_css_class("fractal-inverted-text")
        elif isinstance(widget, Gtk.Entry):
            widget.add_css_class("fractal-inverted-text")
        elif isinstance(widget, Gtk.TreeView):
            widget.add_css_class("fractal-inverted-text")
        
        # Recursively process children
        if hasattr(widget, 'get_first_child'):
            child = widget.get_first_child()
            while child:
                self._invert_widget_colors(child)
                child = child.get_next_sibling()
    
    def regenerate(self, rules: Optional[List[int]] = None):
        """Regenerate the fractal background."""
        self.screensaver.regenerate(rules)
