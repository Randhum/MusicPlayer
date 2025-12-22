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
    """A drawing area that displays a simple animated fractal pattern as a screensaver background."""
    
    def __init__(self, rules: Optional[List[int]] = None, iterations: int = 6,
                 color_scheme: str = "binary", animation_speed: float = 0.02):
        """
        Initialize the fractal screensaver.
        
        Args:
            rules: List of 4 rule values (0-15). If None, uses random rules.
            iterations: Number of iterations (reduced for performance, default 6)
            color_scheme: "binary" (black/white), "grey" (grayscale), or "rgb" (colored)
            animation_speed: Speed of animation (reduced for performance)
        """
        super().__init__()
        
        # Generate random rules if not provided
        if rules is None:
            rules = [random.randint(0, 15) for _ in range(4)]
        
        self.generator = FractalGenerator(rules=rules, iterations=iterations)
        self.color_scheme = color_scheme
        self.animation_time = 0.0
        self.animation_id = None
        
        # Connect draw signal
        self.set_draw_func(self._on_draw)
        
        # Start slow animation timer (much lower FPS)
        self._start_animation()
    
    def _on_draw(self, widget, cr, width: int, height: int):
        """Draw the fractal pattern - simplified for performance."""
        # Clear background
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        
        # Get fractal data (cached by generator)
        fractal = self.generator.generate()
        fractal_size = len(fractal)
        
        # Use larger blocks for much better performance
        block_size = max(4, min(16, int(max(width, height) / fractal_size)))
        
        # Calculate scale
        scale_x = fractal_size / width if width > 0 else 1
        scale_y = fractal_size / height if height > 0 else 1
        
        # Simple binary drawing with blocks - much faster
        for y in range(0, height, block_size):
            for x in range(0, width, block_size):
                # Get fractal value at this position
                fx = min(int(x * scale_x), fractal_size - 1)
                fy = min(int(y * scale_y), fractal_size - 1)
                value = fractal[fy][fx]
                
                # Simple binary color with subtle animation
                base_color = 1.0 if value == 1 else 0.0
                # Very subtle animation
                anim = math.sin(self.animation_time) * 0.1
                color = max(0.0, min(1.0, base_color + anim))
                
                cr.set_source_rgb(color, color, color)
                cr.rectangle(x, y, block_size, block_size)
                cr.fill()
        
        return True
    
    def _start_animation(self):
        """Start the animation timer - much slower for performance."""
        if self.animation_id is None:
            self.animation_id = GLib.timeout_add(200, self._animate)  # 5 FPS - much lighter
    
    def _stop_animation(self):
        """Stop the animation timer."""
        if self.animation_id is not None:
            GLib.source_remove(self.animation_id)
            self.animation_id = None
    
    def _animate(self):
        """Simple animation callback - just update time for color animation."""
        # Simple time-based animation - no rule changes for performance
        self.animation_time += 0.1
        if self.animation_time > math.pi * 2:
            self.animation_time = 0.0
        
        # Only redraw occasionally
        self.queue_draw()
        return True
    
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
    
    def cleanup(self):
        """Clean up animation timer."""
        self._stop_animation()


class FractalBackground(Gtk.Box):
    """A container that displays content on an animated fractal background with inverted text."""
    
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
        
        # Create animated screensaver as background (simplified for performance)
        self.screensaver = FractalScreensaver(
            rules=rules,
            iterations=6,  # Reduced iterations for performance
            color_scheme=color_scheme,
            animation_speed=0.02  # Slower animation for performance
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
    
    def cleanup(self):
        """Clean up the fractal background and stop animation."""
        if self.screensaver:
            self.screensaver.cleanup()
