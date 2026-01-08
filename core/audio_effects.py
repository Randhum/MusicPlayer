"""Audio effects and processing via GStreamer.

This module provides audio effects such as:
- Equalizer (10-band)
- ReplayGain
- Crossfade between tracks
- Audio format conversion/transcoding
"""

# ============================================================================
# Standard Library Imports (alphabetical)
# ============================================================================
from typing import Any, Dict, List, Optional

# ============================================================================
# Third-Party Imports (alphabetical, with version requirements)
# ============================================================================
import gi

gi.require_version("Gst", "1.0")
from gi.repository import Gst

# ============================================================================
# Local Imports (grouped by package, alphabetical)
# ============================================================================
from core.logging import get_logger

logger = get_logger(__name__)


class AudioEffects:
    """
    Audio effects processor using GStreamer.

    Provides equalizer, ReplayGain, and crossfade capabilities.
    """

    def __init__(self) -> None:
        """
        Initialize audio effects.

        Sets up internal state for equalizer, ReplayGain, and crossfade.
        """
        self.equalizer: Optional[Gst.Element] = None
        self.replaygain: Optional[Gst.Element] = None
        self._equalizer_bands: List[float] = [0.0] * 10  # 10-band equalizer
        self._replaygain_enabled = False
        self._crossfade_enabled = False
        self._crossfade_duration = 3.0  # seconds

    def create_equalizer(self) -> Optional[Gst.Element]:
        """
        Create a 10-band equalizer element.

        Returns:
            GStreamer equalizer element, or None if unavailable
        """
        try:
            equalizer = Gst.ElementFactory.make("equalizer-10bands", "equalizer")
            if equalizer:
                self.equalizer = equalizer
                logger.info("Audio effects: 10-band equalizer created")
                return equalizer
            else:
                logger.warning("Audio effects: equalizer-10bands element not available")
                logger.info("Install: emerge -av media-plugins/gst-plugins-good")
        except Exception as e:
            logger.error("Audio effects: Error creating equalizer: %s", e, exc_info=True)
        return None

    def set_equalizer_band(self, band: int, gain: float) -> None:
        """
        Set gain for a specific equalizer band.

        Args:
            band: Band index (0-9 for 10-band equalizer)
            gain: Gain in dB (-24.0 to 12.0, will be clamped)
        """
        if not self.equalizer:
            logger.warning("Audio effects: Equalizer not initialized")
            return

        if band < 0 or band >= 10:
            logger.warning("Audio effects: Invalid band index: %d (must be 0-9)", band)
            return

        gain = max(-24.0, min(12.0, gain))
        self._equalizer_bands[band] = gain

        try:
            # Set band gain property
            # Property names are typically "band0", "band1", etc.
            prop_name = f"band{band}"
            self.equalizer.set_property(prop_name, gain)
            logger.debug("Audio effects: Set band %d to %.2f dB", band, gain)
        except Exception as e:
            logger.error("Audio effects: Error setting band %d: %s", band, e, exc_info=True)

    def get_equalizer_band(self, band: int) -> float:
        """
        Get gain for a specific equalizer band.

        Args:
            band: Band index (0-9)

        Returns:
            Current gain in dB
        """
        if band < 0 or band >= 10:
            return 0.0
        return self._equalizer_bands[band]

    def reset_equalizer(self) -> None:
        """Reset all equalizer bands to 0 dB."""
        for i in range(10):
            self.set_equalizer_band(i, 0.0)
        logger.debug("Audio effects: Equalizer reset")

    def create_replaygain(self) -> Optional[Gst.Element]:
        """
        Create a ReplayGain element.

        Returns:
            GStreamer ReplayGain element, or None if unavailable
        """
        try:
            # Try rgvolume element (ReplayGain volume adjustment)
            replaygain = Gst.ElementFactory.make("rgvolume", "replaygain")
            if replaygain:
                self.replaygain = replaygain
                logger.info("Audio effects: ReplayGain element created")
                return replaygain
            else:
                logger.warning("Audio effects: rgvolume element not available")
                logger.info("Install: emerge -av media-plugins/gst-plugins-good")
        except Exception as e:
            logger.error("Audio effects: Error creating ReplayGain: %s", e, exc_info=True)
        return None

    def set_replaygain_enabled(self, enabled: bool) -> None:
        """
        Enable or disable ReplayGain processing.

        Args:
            enabled: Whether to enable ReplayGain
        """
        self._replaygain_enabled = enabled
        if self.replaygain:
            try:
                # Set ReplayGain mode
                # Typical modes: "track", "album", "auto"
                self.replaygain.set_property("album-mode", False)
                self.replaygain.set_property("target-volume", 0.0)  # 0 dB target
                logger.debug("Audio effects: ReplayGain %s", "enabled" if enabled else "disabled")
            except Exception as e:
                logger.error("Audio effects: Error configuring ReplayGain: %s", e, exc_info=True)

    def create_crossfade(self, duration: float = 3.0) -> Optional[Gst.Element]:
        """
        Create a crossfade element for smooth transitions.

        Args:
            duration: Crossfade duration in seconds

        Returns:
            GStreamer crossfade element, or None if unavailable
        """
        try:
            # Use audiomixer for crossfade effect
            # This requires more complex pipeline setup
            crossfade = Gst.ElementFactory.make("audiomixer", "crossfade")
            if crossfade:
                self._crossfade_duration = duration
                logger.info("Audio effects: Crossfade element created (duration: %.1fs)", duration)
                return crossfade
            else:
                logger.warning("Audio effects: audiomixer element not available")
        except Exception as e:
            logger.error("Audio effects: Error creating crossfade: %s", e, exc_info=True)
        return None

    def set_crossfade_enabled(self, enabled: bool) -> None:
        """
        Enable or disable crossfade between tracks.

        Args:
            enabled: Whether to enable crossfade
        """
        self._crossfade_enabled = enabled
        logger.debug("Audio effects: Crossfade %s", "enabled" if enabled else "disabled")

    def set_crossfade_duration(self, duration: float) -> None:
        """
        Set crossfade duration.

        Args:
            duration: Duration in seconds (0.0 to 10.0, will be clamped)
        """
        self._crossfade_duration = max(0.0, min(10.0, duration))
        logger.debug("Audio effects: Crossfade duration set to %.1fs", self._crossfade_duration)

    def get_preset(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Get a named equalizer preset.

        Args:
            name: Preset name (e.g., "flat", "bass_boost", "treble_boost")

        Returns:
            Dictionary with band gains, or None if preset not found
        """
        presets = {
            "flat": [0.0] * 10,
            "bass_boost": [6.0, 4.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "treble_boost": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 2.0, 4.0, 6.0, 8.0],
            "vocal_boost": [0.0, 0.0, 3.0, 6.0, 6.0, 3.0, 0.0, 0.0, 0.0, 0.0],
            "loudness": [3.0, 2.0, 1.0, 0.0, -1.0, -2.0, -1.0, 0.0, 1.0, 2.0],
        }

        if name.lower() in presets:
            return {"bands": presets[name.lower()]}
        return None

    def apply_preset(self, name: str) -> bool:
        """
        Apply a named equalizer preset.

        Args:
            name: Preset name (e.g., 'flat', 'bass_boost', 'treble_boost')

        Returns:
            True if preset was applied, False if preset not found
        """
        preset = self.get_preset(name)
        if preset:
            bands = preset["bands"]
            for i, gain in enumerate(bands):
                self.set_equalizer_band(i, gain)
            logger.info("Audio effects: Applied preset '%s'", name)
            return True
        logger.warning("Audio effects: Preset '%s' not found", name)
        return False

    def get_equalizer_state(self) -> Dict[str, Any]:
        """
        Get current equalizer state.

        Returns:
            Dictionary with equalizer configuration
        """
        return {"bands": self._equalizer_bands.copy(), "enabled": self.equalizer is not None}

    def cleanup(self) -> None:
        """
        Clean up audio effects resources.

        Releases GStreamer elements and resets state.
        """
        self.equalizer = None
        self.replaygain = None
        logger.debug("Audio effects: Cleaned up")
