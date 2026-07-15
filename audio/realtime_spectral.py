"""
Real-time spectral analysis for live audio.
Produces the same 7 metrics as the offline pipeline (spectral_analysis.py)
but operates on streaming audio chunks from a ring buffer.

Uses pure numpy in the hot path — no librosa dependency at runtime.
"""

import numpy as np
import threading
import time
from dataclasses import dataclass
from typing import Callable, List, Optional
from .ring_buffer import AudioRingBuffer


@dataclass
class LiveFeatureFrame:
    """Per-frame features from real-time analysis.

    Most metric values are normalized to 0-1 via the envelope-follower
    normalizer + output smoother. `centroid_hz` is the unnormalized
    raw spectral centroid in Hz, kept alongside so downstream code that
    needs an absolute frequency (e.g. live auto-color hue mapping)
    doesn't have to invert a normalized rank.
    """
    timestamp: float    # seconds since analysis start
    flux: float         # spectral flux (onset strength)
    transient: float    # transient sharpness (peakiness)
    richness: float     # spectral richness (bandwidth + flatness)
    vocal: float        # vocal presence proxy (band energy + MFCC delta)
    centroid: float     # spectral centroid (normalized 0-1, for UI display)
    rms: float          # RMS energy
    contrast: float     # spectral contrast
    centroid_hz: float = 0.0  # spectral centroid in Hz (unnormalized)
    # Onset strength for beat tracking: per-band (low/mid/high) positive
    # log-magnitude flux, each band saturated against its own recent peak
    # and reduced to its rising edge, then combined with the high band
    # down-weighted. This makes an onset spike near-equal for a kick
    # (narrowband, low) and a snare (broadband, mid) so a backbeat's
    # every-beat periodicity survives, while hat/cymbal subdivision stays
    # visibly weaker (band weight) instead of being equalized into a
    # false double tempo. Range is ~0..2.4 (sum of band weights), NOT the
    # normalized 0-1 of `flux` above; deliberately unsmoothed - the
    # display flux passes a 0.6 s smoother that destroys beat-rate
    # periodicity (its autocorrelation collapses to the shortest lag).
    #
    # Computed on the UNDECIMATED signal at the analyzer's
    # `beat_frame_rate_hz` (~86 Hz for 44100 input): `flux_raw_hops`
    # carries every beat-flux hop that elapsed during this (43 Hz)
    # feature frame, oldest first; `flux_raw` is their max, kept for
    # single-value consumers. The doubled rate matters because tempo
    # resolution is lag-limited: at 43 Hz a 190 BPM beat is ~13.6
    # frames, at 86 Hz it is ~27.
    flux_raw: float = 0.0
    flux_raw_hops: tuple = ()


class _EMANormalizer:
    """Envelope-follower normalizer for live signal scaling.

    Tracks running peak (max) and trough (min) with fast attack on the
    extremes and slow decay back toward the centre, so the normalisation
    range represents the actual dynamic range of recent audio rather than
    collapsing to a moving average.
    """

    def __init__(self, decay_seconds: float = 15.0, update_rate_hz: float = 86.0):
        # Slow decay alpha: how fast running_max drifts down (or running_min up)
        # toward the value when the value is *not* a new extreme.
        self._alpha_decay = 1.0 - np.exp(-1.0 / (decay_seconds * update_rate_hz))
        # Fast attack alpha: how fast extremes are captured. Short time
        # constant (~150 ms) so peaks are followed without latching onto noise.
        self._alpha_attack = 1.0 - np.exp(-1.0 / (0.15 * update_rate_hz))
        self._running_min = None
        self._running_max = None

    def normalize(self, value: float) -> float:
        if self._running_min is None:
            self._running_min = value
            self._running_max = value + 1e-3
            return 0.5

        # Max: fast attack on new peaks, slow decay back down.
        if value > self._running_max:
            self._running_max += self._alpha_attack * (value - self._running_max)
        else:
            self._running_max += self._alpha_decay * (value - self._running_max)

        # Min: fast attack on new troughs, slow drift back up.
        if value < self._running_min:
            self._running_min += self._alpha_attack * (value - self._running_min)
        else:
            self._running_min += self._alpha_decay * (value - self._running_min)

        span = self._running_max - self._running_min
        if span < 1e-6:
            return 0.5  # No useful range yet — keep meters quiet.

        return float(np.clip((value - self._running_min) / span, 0.0, 1.0))

    def set_range(self, min_val: float, max_val: float):
        """Pre-set normalization range (e.g. from offline analysis)."""
        self._running_min = min_val
        self._running_max = max_val


class _OutputSmoother:
    """Single-pole low-pass filter on the normalised metric output.

    Decouples the visual + decision-making smoothness from the underlying
    analysis frame rate. Without this, per-frame fluctuations dominate the
    readout even when the normaliser range is stable.
    """

    def __init__(self, time_constant_seconds: float = 0.6, update_rate_hz: float = 86.0):
        self._alpha = 1.0 - np.exp(-1.0 / (time_constant_seconds * update_rate_hz))
        self._state: Optional[float] = None

    def smooth(self, value: float) -> float:
        if self._state is None:
            self._state = value
        else:
            self._state += self._alpha * (value - self._state)
        return float(self._state)

    def reset(self):
        self._state = None


class RealtimeSpectralAnalyzer:
    """Processes live audio from a ring buffer and emits per-frame spectral features.

    Runs a dedicated processing thread that reads hop_length samples at a time,
    maintains a sliding STFT window, and computes 7 metrics matching the offline
    pipeline in spectral_analysis.py.
    """

    def __init__(self, sample_rate: int = 44100, n_fft: int = 2048, hop_length: int = 512):
        """
        Args:
            sample_rate: Expected input sample rate
            n_fft: FFT window size in samples
            hop_length: Hop between consecutive frames in samples
        """
        self.sample_rate = sample_rate
        self.n_fft = n_fft
        self.hop_length = hop_length

        # Internal analysis rate — decimate to 22050 for consistency with offline pipeline
        self._decimate = sample_rate > 22050
        self._analysis_sr = sample_rate // 2 if self._decimate else sample_rate

        # Pre-compute window and frequency bins
        self._window = np.hanning(n_fft).astype(np.float32)
        self._freq_bins = np.fft.rfftfreq(n_fft, d=1.0 / self._analysis_sr)
        self._nyquist = self._analysis_sr / 2.0

        # State for sliding STFT
        self._prev_magnitude = None
        self._prev_magnitude_log = None  # separate state for beat flux
        self._sliding_buffer = np.zeros(n_fft, dtype=np.float32)

        # Beat-flux path (see LiveFeatureFrame.flux_raw): runs on the
        # UNDECIMATED signal with its own sliding STFT (n_fft at the
        # native rate, hop = hop_length native samples -> ~86 Hz for
        # 44100 input), because tempo resolution is lag-limited and the
        # decimated 43 Hz grid is too coarse above ~150 BPM. Band split:
        # kick energy lives <200 Hz, snare/vocal body 200-4000 Hz, hats
        # and cymbals above. Per-band saturation refs follow each band's
        # recent peak with a ~3 s decay.
        # The beat FFT window is 2x n_fft so its span in SECONDS (~93 ms
        # at 44100) matches the decimated feature path: a 46 ms window
        # resolves every micro-transient of sustained instruments and
        # buries the beat in onset noise on real music.
        self._beat_hop = hop_length
        self._beat_n_fft = n_fft * 2
        self._beat_window = np.hanning(self._beat_n_fft).astype(np.float32)
        self._beat_buffer = np.zeros(self._beat_n_fft, dtype=np.float32)
        self._beat_pending_samples = np.zeros(0, dtype=np.float32)
        self._pending_beat_flux: List[float] = []
        beat_bins = np.fft.rfftfreq(self._beat_n_fft, d=1.0 / sample_rate)
        self._beat_band_masks = [
            beat_bins < 200.0,
            (beat_bins >= 200.0) & (beat_bins < 4000.0),
            beat_bins >= 4000.0,
        ]
        self._beat_band_weights = (1.0, 1.0, 0.4)
        self._beat_band_refs = [0.0, 0.0, 0.0]
        self._beat_band_prev = [0.0, 0.0, 0.0]
        self._beat_ref_decay = float(np.exp(-1.0 / (3.0 * self.beat_frame_rate_hz)))

        # MFCC delta tracking for vocal proxy (circular buffer of 10 frames)
        self._mfcc_history_size = 10
        self._mfcc_history = np.zeros((self._mfcc_history_size, 13), dtype=np.float32)
        self._mfcc_write_idx = 0
        self._mfcc_count = 0

        # Transient EMA for peakiness ratio
        self._flux_ema = 0.0
        self._flux_ema_alpha = 0.1

        # Normalizers (one per metric). Decay time governs how long peaks
        # and troughs influence the dynamic-range estimate — long enough to
        # represent a song section, not just the last second.
        update_hz = self._analysis_sr / hop_length
        self._norm_flux = _EMANormalizer(decay_seconds=15.0, update_rate_hz=update_hz)
        self._norm_transient = _EMANormalizer(decay_seconds=15.0, update_rate_hz=update_hz)
        self._norm_richness = _EMANormalizer(decay_seconds=15.0, update_rate_hz=update_hz)
        self._norm_vocal = _EMANormalizer(decay_seconds=15.0, update_rate_hz=update_hz)
        self._norm_centroid = _EMANormalizer(decay_seconds=15.0, update_rate_hz=update_hz)
        self._norm_rms = _EMANormalizer(decay_seconds=15.0, update_rate_hz=update_hz)
        self._norm_contrast = _EMANormalizer(decay_seconds=15.0, update_rate_hz=update_hz)

        # Output smoothers — applied after normalisation so the emitted
        # metrics have gradual curves rather than per-frame jitter.
        smooth_tc = 0.6
        self._smooth_flux = _OutputSmoother(time_constant_seconds=smooth_tc, update_rate_hz=update_hz)
        self._smooth_transient = _OutputSmoother(time_constant_seconds=smooth_tc, update_rate_hz=update_hz)
        self._smooth_richness = _OutputSmoother(time_constant_seconds=smooth_tc, update_rate_hz=update_hz)
        self._smooth_vocal = _OutputSmoother(time_constant_seconds=smooth_tc, update_rate_hz=update_hz)
        self._smooth_centroid = _OutputSmoother(time_constant_seconds=smooth_tc, update_rate_hz=update_hz)
        self._smooth_rms = _OutputSmoother(time_constant_seconds=smooth_tc, update_rate_hz=update_hz)
        self._smooth_contrast = _OutputSmoother(time_constant_seconds=smooth_tc, update_rate_hz=update_hz)

        # Spectral contrast band edges (7 octave bands)
        self._contrast_bands = self._compute_contrast_band_edges()

        # Vocal band indices (300-3400 Hz)
        self._vocal_lo = np.searchsorted(self._freq_bins, 300)
        self._vocal_hi = np.searchsorted(self._freq_bins, 3400)

        # Mel filterbank for lightweight MFCC (13 coefficients, 40 mel filters)
        self._mel_filterbank = self._build_mel_filterbank(n_mels=40)

        # Subscribers
        self._callbacks: List[Callable[[LiveFeatureFrame], None]] = []
        self._callbacks_lock = threading.Lock()

        # Thread control
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._ring_buffer: Optional[AudioRingBuffer] = None
        self._start_time = 0.0

    @property
    def frame_rate_hz(self) -> float:
        """LiveFeatureFrames emitted per second of audio.

        With the default 44100 Hz input this is 22050/512 = ~43.07 Hz
        (the 2:1 decimation halves the effective rate) - NOT the ~86 Hz
        a 44100/512 hop would suggest. Consumers that convert frame
        counts to time must use this value.
        """
        return self._analysis_sr / self.hop_length

    @property
    def beat_frame_rate_hz(self) -> float:
        """Beat-flux hops per second of audio (undecimated path).

        44100/512 = ~86.13 Hz for the default input. This is the rate to
        construct AutoBPMDetector with when consuming `flux_raw_hops`.
        """
        return self.sample_rate / self.hop_length

    def start(self, ring_buffer: AudioRingBuffer) -> None:
        """Start the analysis thread.

        Args:
            ring_buffer: Ring buffer to read audio from
        """
        if self._thread and self._thread.is_alive():
            return

        self._ring_buffer = ring_buffer
        self._stop_event.clear()
        self._start_time = time.monotonic()
        self._reset_state()

        self._thread = threading.Thread(
            target=self._processing_loop,
            name="RealtimeSpectralAnalyzer",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the analysis thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)
            self._thread = None

    def subscribe(self, callback: Callable[[LiveFeatureFrame], None]) -> None:
        """Subscribe to feature updates.

        Callbacks are called on the analysis thread. For Qt thread safety,
        use LiveFeatureBridge instead.
        """
        with self._callbacks_lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def unsubscribe(self, callback: Callable[[LiveFeatureFrame], None]) -> None:
        """Unsubscribe from feature updates."""
        with self._callbacks_lock:
            if callback in self._callbacks:
                self._callbacks.remove(callback)

    def set_calibration_range(self, metric: str, min_val: float, max_val: float) -> None:
        """Pre-set normalization range for a metric.

        Useful when offline analysis results are available to seed
        the normalizer with known dynamic ranges.

        Args:
            metric: One of 'flux', 'transient', 'richness', 'vocal', 'centroid', 'rms', 'contrast'
            min_val: Minimum expected raw value
            max_val: Maximum expected raw value
        """
        normalizer = getattr(self, f'_norm_{metric}', None)
        if normalizer:
            normalizer.set_range(min_val, max_val)

    def _reset_state(self):
        """Reset internal state for a fresh start."""
        self._prev_magnitude = None
        self._prev_magnitude_log = None
        self._beat_buffer[:] = 0
        self._beat_pending_samples = np.zeros(0, dtype=np.float32)
        self._pending_beat_flux.clear()
        self._beat_band_refs = [0.0, 0.0, 0.0]
        self._beat_band_prev = [0.0, 0.0, 0.0]

    def _push_beat_samples(self, samples: np.ndarray) -> None:
        """Feed undecimated mono samples to the beat-flux path.

        Called from the processing loop BEFORE decimation with the same
        audio the feature path consumes. Produces one band-combined
        onset value per `hop_length` native samples (~86 Hz); values
        accumulate in `_pending_beat_flux` until the next feature frame
        collects them into `flux_raw_hops`.
        """
        self._beat_pending_samples = np.concatenate(
            [self._beat_pending_samples, samples.astype(np.float32)])
        hop = self._beat_hop
        n_fft = self._beat_buffer.size
        while self._beat_pending_samples.size >= hop:
            chunk = self._beat_pending_samples[:hop]
            self._beat_pending_samples = self._beat_pending_samples[hop:]
            self._beat_buffer[:n_fft - hop] = self._beat_buffer[hop:]
            self._beat_buffer[n_fft - hop:] = chunk

            mag_log = np.log1p(np.abs(
                np.fft.rfft(self._beat_buffer * self._beat_window)))
            if self._prev_magnitude_log is None:
                self._prev_magnitude_log = mag_log
                self._pending_beat_flux.append(0.0)
                continue
            dlog = mag_log - self._prev_magnitude_log
            self._prev_magnitude_log = mag_log
            dlog[dlog < 0] = 0
            onset = 0.0
            # Per band: saturate against the band's recent peak
            # (equalizes kick vs snare spike heights), keep only the
            # rising edge (equalizes spike shapes: a snare's noise tail
            # keeps producing "new energy" for several frames, a kick
            # doesn't), then combine with hats/cymbals down-weighted so
            # subdivision stays distinguishable from the beat.
            for i, (mask, w) in enumerate(zip(self._beat_band_masks,
                                              self._beat_band_weights)):
                v = float(dlog[mask].sum())
                ref = max(v, self._beat_band_refs[i] * self._beat_ref_decay)
                self._beat_band_refs[i] = ref
                sat = v / (v + 0.5 * ref) if ref > 0 else 0.0
                onset += w * max(0.0, sat - self._beat_band_prev[i])
                self._beat_band_prev[i] = sat
            self._pending_beat_flux.append(onset)
        self._sliding_buffer[:] = 0
        self._flux_ema = 0.0
        self._mfcc_history[:] = 0
        self._mfcc_write_idx = 0
        self._mfcc_count = 0
        self._smooth_flux.reset()
        self._smooth_transient.reset()
        self._smooth_richness.reset()
        self._smooth_vocal.reset()
        self._smooth_centroid.reset()
        self._smooth_rms.reset()
        self._smooth_contrast.reset()

    def _processing_loop(self):
        """Main analysis loop — runs on dedicated thread."""
        hop = self.hop_length
        # Account for decimation: need 2x samples from ring buffer if decimating
        read_size = hop * 2 if self._decimate else hop
        interval = hop / self._analysis_sr  # time between frames

        while not self._stop_event.is_set():
            if self._ring_buffer.available() < read_size:
                # Not enough data yet — sleep for half a hop
                time.sleep(interval * 0.5)
                continue

            # Read samples
            raw = self._ring_buffer.read_consume(read_size)
            if raw.shape[0] < read_size:
                time.sleep(interval * 0.5)
                continue

            # Convert to mono if multi-channel
            if raw.ndim == 2 and raw.shape[1] > 1:
                samples = raw.mean(axis=1)
            elif raw.ndim == 2:
                samples = raw[:, 0]
            else:
                samples = raw

            # Beat flux runs on the undecimated signal (finer tempo
            # resolution); must see the samples before decimation.
            self._push_beat_samples(samples)

            # Decimate 2:1 if needed (simple averaging, fast)
            if self._decimate:
                samples = (samples[0::2] + samples[1::2]) * 0.5

            # Slide the buffer
            self._sliding_buffer[:self.n_fft - hop] = self._sliding_buffer[hop:]
            self._sliding_buffer[self.n_fft - hop:] = samples[:hop]

            # Compute features
            frame = self._compute_frame()
            if frame is not None:
                with self._callbacks_lock:
                    for cb in self._callbacks:
                        try:
                            cb(frame)
                        except Exception as e:
                            print(f"Error in spectral callback: {e}")

    def _compute_frame(self) -> Optional[LiveFeatureFrame]:
        """Compute all 7 features for the current sliding window."""
        # Apply window and FFT
        windowed = self._sliding_buffer * self._window
        spectrum = np.fft.rfft(windowed)
        magnitude = np.abs(spectrum)
        power = magnitude ** 2

        # Collect the beat-flux hops that elapsed since the last frame
        # (produced by _push_beat_samples on the undecimated signal).
        beat_hops = tuple(self._pending_beat_flux)
        self._pending_beat_flux.clear()
        beat_flux = max(beat_hops) if beat_hops else 0.0

        # Avoid division by zero
        mag_sum = magnitude.sum()
        if mag_sum < 1e-10:
            # Silence — return zeros
            return LiveFeatureFrame(
                timestamp=time.monotonic() - self._start_time,
                flux=0.0, transient=0.0, richness=0.0,
                vocal=0.0, centroid=0.0, rms=0.0, contrast=0.0,
                centroid_hz=0.0, flux_raw=beat_flux,
                flux_raw_hops=beat_hops,
            )

        # 1. Spectral flux
        if self._prev_magnitude is not None:
            diff = magnitude - self._prev_magnitude
            diff[diff < 0] = 0  # half-wave rectification
            raw_flux = np.sqrt(np.sum(diff ** 2))
        else:
            raw_flux = 0.0
        self._prev_magnitude = magnitude.copy()

        # 2. Transient sharpness (flux / EMA of flux)
        self._flux_ema = (1 - self._flux_ema_alpha) * self._flux_ema + self._flux_ema_alpha * raw_flux
        raw_transient = raw_flux / (self._flux_ema + 1e-10)

        # 3. Spectral centroid
        raw_centroid = np.sum(self._freq_bins * magnitude) / mag_sum

        # 4. Spectral richness = 0.6 * bandwidth + 0.4 * flatness
        centroid_hz = raw_centroid
        deviation = self._freq_bins - centroid_hz
        raw_bandwidth = np.sqrt(np.sum(magnitude * deviation ** 2) / mag_sum)

        # Spectral flatness: geometric mean / arithmetic mean of power spectrum
        log_power = np.log(power + 1e-10)
        geometric_mean = np.exp(np.mean(log_power))
        arithmetic_mean = np.mean(power) + 1e-10
        raw_flatness = geometric_mean / arithmetic_mean
        raw_richness = 0.6 * raw_bandwidth + 0.4 * raw_flatness

        # 5. RMS energy
        raw_rms = np.sqrt(np.mean(self._sliding_buffer ** 2))

        # 6. Spectral contrast (peak-to-valley across bands)
        raw_contrast = self._compute_spectral_contrast(power)

        # 7. Vocal presence proxy
        raw_vocal = self._compute_vocal_proxy(magnitude, power)

        # Normalize then smooth each metric so the emitted values have
        # gradual curves rather than per-frame binary swings. centroid_hz
        # is the unnormalized raw centroid in Hz — consumers that need
        # an absolute frequency (live auto-color) read this directly.
        timestamp = time.monotonic() - self._start_time
        return LiveFeatureFrame(
            timestamp=timestamp,
            flux=self._smooth_flux.smooth(self._norm_flux.normalize(raw_flux)),
            transient=self._smooth_transient.smooth(self._norm_transient.normalize(raw_transient)),
            richness=self._smooth_richness.smooth(self._norm_richness.normalize(raw_richness)),
            vocal=self._smooth_vocal.smooth(self._norm_vocal.normalize(raw_vocal)),
            centroid=self._smooth_centroid.smooth(self._norm_centroid.normalize(raw_centroid)),
            rms=self._smooth_rms.smooth(self._norm_rms.normalize(raw_rms)),
            contrast=self._smooth_contrast.smooth(self._norm_contrast.normalize(raw_contrast)),
            centroid_hz=float(raw_centroid),
            flux_raw=beat_flux,
            flux_raw_hops=beat_hops,
        )

    def _compute_spectral_contrast(self, power: np.ndarray) -> float:
        """Compute spectral contrast: peak-to-valley ratio across 7 bands."""
        contrasts = []
        for lo, hi in self._contrast_bands:
            if hi <= lo:
                continue
            band = power[lo:hi]
            if len(band) < 2:
                continue
            sorted_band = np.sort(band)
            n = len(sorted_band)
            bottom_10 = max(1, n // 10)
            top_10 = max(1, n // 10)
            valley = np.mean(sorted_band[:bottom_10]) + 1e-10
            peak = np.mean(sorted_band[-top_10:])
            contrasts.append(np.log10(peak / valley + 1e-10))

        return float(np.mean(contrasts)) if contrasts else 0.0

    def _compute_vocal_proxy(self, magnitude: np.ndarray, power: np.ndarray) -> float:
        """Lightweight vocal presence proxy.

        Combines:
        - Vocal band energy ratio (300-3400 Hz)
        - MFCC delta variance (phoneme change detection)

        Much cheaper than full HPSS which requires O(n_fft^2) median filtering.
        """
        # Vocal band energy ratio
        total_energy = np.sum(power) + 1e-10
        vocal_energy = np.sum(power[self._vocal_lo:self._vocal_hi])
        band_ratio = vocal_energy / total_energy

        # Lightweight MFCC: apply mel filterbank to power spectrum, then DCT
        mel_spec = self._mel_filterbank @ power
        mel_spec = np.log(mel_spec + 1e-10)
        # Type-II DCT approximation using matrix multiply (pre-computed would be faster,
        # but 13 coefficients from 40 filters is cheap enough)
        n_mfcc = 13
        n_mels = mel_spec.shape[0]
        mfcc = np.zeros(n_mfcc, dtype=np.float32)
        for k in range(n_mfcc):
            mfcc[k] = np.sum(mel_spec * np.cos(np.pi * k * (np.arange(n_mels) + 0.5) / n_mels))

        # Store in circular buffer
        self._mfcc_history[self._mfcc_write_idx] = mfcc
        self._mfcc_write_idx = (self._mfcc_write_idx + 1) % self._mfcc_history_size
        self._mfcc_count = min(self._mfcc_count + 1, self._mfcc_history_size)

        # Compute delta variance (how much MFCCs are changing)
        if self._mfcc_count >= 3:
            active = self._mfcc_history[:self._mfcc_count]
            deltas = np.diff(active, axis=0)
            delta_var = np.mean(np.sqrt(np.mean(deltas ** 2, axis=1)))
        else:
            delta_var = 0.0

        # Combine: 50% band energy + 50% MFCC delta variance
        return 0.5 * band_ratio + 0.5 * delta_var

    def _compute_contrast_band_edges(self) -> List[tuple]:
        """Compute frequency bin index ranges for 7 octave bands."""
        # Standard octave bands roughly: 64, 128, 256, 512, 1024, 2048, 4096, 8192 Hz
        edges_hz = [64, 128, 256, 512, 1024, 2048, 4096, min(8192, self._nyquist)]
        bands = []
        for i in range(len(edges_hz) - 1):
            lo = np.searchsorted(self._freq_bins, edges_hz[i])
            hi = np.searchsorted(self._freq_bins, edges_hz[i + 1])
            bands.append((lo, hi))
        return bands

    def _build_mel_filterbank(self, n_mels: int = 40) -> np.ndarray:
        """Build a mel filterbank matrix (n_mels x n_fft_bins).

        Simplified mel filterbank — no librosa dependency.
        """
        n_fft_bins = self.n_fft // 2 + 1
        f_min = 0.0
        f_max = self._nyquist

        # Mel scale conversion
        def hz_to_mel(hz):
            return 2595.0 * np.log10(1.0 + hz / 700.0)

        def mel_to_hz(mel):
            return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)

        mel_min = hz_to_mel(f_min)
        mel_max = hz_to_mel(f_max)
        mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
        hz_points = mel_to_hz(mel_points)

        # Convert to FFT bin indices
        bin_points = np.floor((self.n_fft + 1) * hz_points / self._analysis_sr).astype(int)

        filterbank = np.zeros((n_mels, n_fft_bins), dtype=np.float32)
        for m in range(n_mels):
            f_left = bin_points[m]
            f_center = bin_points[m + 1]
            f_right = bin_points[m + 2]

            # Rising slope
            for k in range(f_left, f_center):
                if k < n_fft_bins and f_center != f_left:
                    filterbank[m, k] = (k - f_left) / (f_center - f_left)

            # Falling slope
            for k in range(f_center, f_right):
                if k < n_fft_bins and f_right != f_center:
                    filterbank[m, k] = (f_right - k) / (f_right - f_center)

        return filterbank
