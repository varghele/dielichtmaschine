"""
Waveform analysis and peak extraction for visualization.
Generates multi-resolution peak data for efficient waveform display at different zoom levels.
"""

import numpy as np
import os
import json
import hashlib
from typing import Optional, Tuple, List
from dataclasses import dataclass, asdict
from .audio_file import AudioFile


@dataclass
class WaveformPeaks:
    """Container for waveform peak data at a specific resolution"""
    resolution: int  # Samples per peak
    min_peaks: List[float]  # Minimum values
    max_peaks: List[float]  # Maximum values
    rms_peaks: List[float]  # RMS values for visual intensity


class WaveformData:
    """Complete waveform data with multiple resolutions"""

    def __init__(self, file_path: str, sample_rate: int, duration: float):
        self.file_path = file_path
        self.sample_rate = sample_rate
        self.duration = duration
        self.peak_levels: dict[int, WaveformPeaks] = {}  # resolution -> peaks

    def add_peak_level(self, peaks: WaveformPeaks):
        """Add a peak level to the waveform data"""
        self.peak_levels[peaks.resolution] = peaks

    def get_peaks_for_zoom(self, pixels_per_second: float) -> Optional[WaveformPeaks]:
        """
        Get the most appropriate peak level for a given zoom level

        Args:
            pixels_per_second: Current display resolution (pixels per second)

        Returns:
            WaveformPeaks object or None if no suitable resolution available
        """
        if not self.peak_levels:
            return None

        # Calculate samples per pixel
        samples_per_pixel = self.sample_rate / pixels_per_second

        # Find the peak level with resolution closest to but not less than samples_per_pixel
        suitable_resolutions = [res for res in self.peak_levels.keys()
                                if res >= samples_per_pixel * 0.5]

        if not suitable_resolutions:
            # Fall back to highest resolution available
            return self.peak_levels[max(self.peak_levels.keys())]

        # Use the finest suitable resolution
        best_resolution = min(suitable_resolutions)
        return self.peak_levels[best_resolution]


class WaveformAnalyzer:
    """Analyzes audio files and generates waveform peak data"""

    # Standard resolutions (samples per peak)
    # These correspond to different zoom levels
    RESOLUTIONS = [
        128,      # ~3ms at 44.1kHz - very zoomed in
        512,      # ~11ms - zoomed in
        2048,     # ~46ms - normal
        8192,     # ~186ms - zoomed out
        32768,    # ~743ms - very zoomed out
    ]

    def __init__(self, cache_dir: Optional[str] = None):
        """
        Initialize waveform analyzer

        Args:
            cache_dir: Directory to store cached waveform data
        """
        self.cache_dir = cache_dir or os.path.join(os.path.expanduser("~"), ".qlcautoshow", "waveform_cache")
        os.makedirs(self.cache_dir, exist_ok=True)

    def analyze_file(self, audio_file: AudioFile, force_regenerate: bool = False) -> Optional[WaveformData]:
        """
        Analyze an audio file and generate waveform data

        Args:
            audio_file: Loaded AudioFile object
            force_regenerate: Force regeneration even if cache exists

        Returns:
            WaveformData object or None on failure
        """
        if not audio_file.is_loaded():
            print("Audio file not loaded")
            return None

        # Check cache first
        if not force_regenerate:
            cached_data = self._load_from_cache(audio_file.file_path)
            if cached_data:
                return cached_data

        # Generate waveform data
        waveform_data = WaveformData(
            audio_file.file_path,
            audio_file.sample_rate,
            audio_file.duration
        )

        # Generate peaks at each resolution
        for resolution in self.RESOLUTIONS:
            peaks = self._generate_peaks(audio_file.audio_data, resolution)
            if peaks:
                waveform_data.add_peak_level(peaks)

        # Cache the results
        self._save_to_cache(waveform_data)

        return waveform_data

    def _generate_peaks(self, audio_data: np.ndarray, resolution: int) -> Optional[WaveformPeaks]:
        """
        Generate peak data at a specific resolution

        Args:
            audio_data: Audio data as numpy array (frames, channels)
            resolution: Number of samples per peak

        Returns:
            WaveformPeaks object
        """
        try:
            # Convert stereo to mono for waveform display (simple average)
            if audio_data.shape[1] == 2:
                mono_data = np.mean(audio_data, axis=1)
            else:
                mono_data = audio_data[:, 0]

            # Calculate number of peaks
            num_peaks = (len(mono_data) + resolution - 1) // resolution

            min_peaks = []
            max_peaks = []
            rms_peaks = []

            # Generate peaks
            for i in range(num_peaks):
                start_idx = i * resolution
                end_idx = min(start_idx + resolution, len(mono_data))

                chunk = mono_data[start_idx:end_idx]

                if len(chunk) > 0:
                    min_peaks.append(float(np.min(chunk)))
                    max_peaks.append(float(np.max(chunk)))
                    rms_peaks.append(float(np.sqrt(np.mean(chunk ** 2))))
                else:
                    min_peaks.append(0.0)
                    max_peaks.append(0.0)
                    rms_peaks.append(0.0)

            return WaveformPeaks(
                resolution=resolution,
                min_peaks=min_peaks,
                max_peaks=max_peaks,
                rms_peaks=rms_peaks
            )

        except Exception as e:
            print(f"Error generating peaks at resolution {resolution}: {e}")
            return None

    def _get_cache_path(self, file_path: str) -> str:
        """Generate cache file path for an audio file"""
        # Use hash of file path + modification time for cache key
        try:
            mtime = os.path.getmtime(file_path)
            cache_key = f"{file_path}_{mtime}"
        except:
            cache_key = file_path

        file_hash = hashlib.md5(cache_key.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{file_hash}.waveform")

    def _save_to_cache(self, waveform_data: WaveformData):
        """Save waveform data to cache.

        Binary npz since 2026-07-16: the old JSON cache serialized
        ~500k floats per song (a multi-second dump, ~1 s parse), and
        the write was NOT atomic - an interrupted write left a
        truncated file that failed to parse forever after, so every
        song load re-analyzed and re-wrote. npz round-trips in tens of
        milliseconds and the tmp+replace write can never leave a torn
        cache. Old JSON caches simply miss and regenerate once.
        """
        try:
            cache_path = self._get_cache_path(waveform_data.file_path)
            arrays = {}
            for resolution, peaks in waveform_data.peak_levels.items():
                arrays[f"min_{resolution}"] = np.asarray(peaks.min_peaks,
                                                         dtype=np.float32)
                arrays[f"max_{resolution}"] = np.asarray(peaks.max_peaks,
                                                         dtype=np.float32)
                arrays[f"rms_{resolution}"] = np.asarray(peaks.rms_peaks,
                                                         dtype=np.float32)
            arrays["_meta_sample_rate"] = np.array(
                [waveform_data.sample_rate], dtype=np.float64)
            arrays["_meta_duration"] = np.array(
                [waveform_data.duration], dtype=np.float64)
            tmp = cache_path + ".tmp"
            with open(tmp, "wb") as f:
                np.savez(f, **arrays)
            os.replace(tmp, cache_path)
            return
        except Exception as e:
            print(f"Error saving waveform cache: {e}")

    def _load_from_cache(self, file_path: str) -> Optional[WaveformData]:
        """Load waveform data from the npz cache. Anything unreadable
        (including a pre-2026-07-16 JSON cache) misses quietly and
        regenerates."""
        try:
            cache_path = self._get_cache_path(file_path)

            if not os.path.exists(cache_path):
                return None

            with np.load(cache_path, allow_pickle=False) as data:
                waveform_data = WaveformData(
                    file_path,
                    float(data["_meta_sample_rate"][0]),
                    float(data["_meta_duration"][0]),
                )
                resolutions = sorted(
                    int(name[4:]) for name in data.files
                    if name.startswith("min_"))
                if not resolutions:
                    return None
                for resolution in resolutions:
                    waveform_data.add_peak_level(WaveformPeaks(
                        resolution=resolution,
                        min_peaks=data[f"min_{resolution}"],
                        max_peaks=data[f"max_{resolution}"],
                        rms_peaks=data[f"rms_{resolution}"],
                    ))
            return waveform_data

        except Exception:
            return None      # miss: regenerate (and re-save as npz)

    def clear_cache(self):
        """Clear all cached waveform data"""
        try:
            for filename in os.listdir(self.cache_dir):
                if filename.endswith('.waveform'):
                    os.remove(os.path.join(self.cache_dir, filename))
        except Exception as e:
            print(f"Error clearing waveform cache: {e}")


def generate_simple_overview(audio_data: np.ndarray, target_width: int = 1000) -> Tuple[List[float], List[float]]:
    """
    Generate a simple waveform overview for quick visualization

    Args:
        audio_data: Audio data as numpy array (frames, channels)
        target_width: Target number of peaks to generate

    Returns:
        Tuple of (min_peaks, max_peaks) lists
    """
    try:
        # Convert stereo to mono
        if audio_data.shape[1] == 2:
            mono_data = np.mean(audio_data, axis=1)
        else:
            mono_data = audio_data[:, 0]

        # Calculate samples per peak
        samples_per_peak = max(1, len(mono_data) // target_width)

        min_peaks = []
        max_peaks = []

        for i in range(target_width):
            start_idx = i * samples_per_peak
            end_idx = min(start_idx + samples_per_peak, len(mono_data))

            if start_idx < len(mono_data):
                chunk = mono_data[start_idx:end_idx]
                if len(chunk) > 0:
                    min_peaks.append(float(np.min(chunk)))
                    max_peaks.append(float(np.max(chunk)))
                else:
                    min_peaks.append(0.0)
                    max_peaks.append(0.0)
            else:
                break

        return min_peaks, max_peaks

    except Exception as e:
        print(f"Error generating simple overview: {e}")
        return [], []
