"""Audio analysis module for algorithmic show generation.

Extracts spectral flux, transient sharpness, spectral richness,
vocal presence, and spectral centroid from audio files, segmented
by the operator-provided song structure.
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Tuple, Optional

try:
    import librosa
    LIBROSA_AVAILABLE = True
except ImportError:
    LIBROSA_AVAILABLE = False


@dataclass
class SectionAnalysis:
    """Audio analysis results for one section of a song."""
    name: str
    start_time: float
    end_time: float
    spectral_flux_avg: float = 0.0
    spectral_flux_envelope: List[float] = field(default_factory=list)
    transient_sharpness: float = 0.0       # 0.0 (sustained) to 1.0 (percussive)
    spectral_richness: float = 0.0         # 0.0 (sparse) to 1.0 (dense)
    vocal_presence: float = 0.0            # 0.0 to 1.0 (HPSS+MFCC delta vocal score)
    spectral_centroid_avg: float = 0.0     # Hz, for color mapping
    rms_energy: float = 0.0               # 0.0 to 1.0, normalized RMS loudness
    spectral_contrast_avg: float = 0.0    # 0.0 to 1.0, avg peak-to-valley across bands


@dataclass
class SongAnalysis:
    """Complete audio analysis for a song."""
    sections: List[SectionAnalysis] = field(default_factory=list)
    global_flux_range: Tuple[float, float] = (0.0, 1.0)
    sample_rate: int = 22050
    duration: float = 0.0


def analyze_song(audio_path: str, song_structure) -> SongAnalysis:
    """Run full spectral analysis on a song file.

    Args:
        audio_path: Path to the audio file (mp3, wav, etc.)
        song_structure: SongStructure instance with parts defining section boundaries

    Returns:
        SongAnalysis with per-section results

    Raises:
        ImportError: If librosa is not installed
        FileNotFoundError: If audio file doesn't exist
    """
    if not LIBROSA_AVAILABLE:
        raise ImportError("librosa is required for audio analysis. Install with: pip install librosa")

    # Load audio
    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    # Compute global features
    hop_length = 512
    n_fft = 2048

    # Spectral flux (onset strength envelope)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length, n_fft=n_fft)

    # Onset detection for transient sharpness
    onset_frames = librosa.onset.onset_detect(
        y=y, sr=sr, hop_length=hop_length, onset_envelope=onset_env, backtrack=True
    )
    onset_times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)

    # Spectral centroid
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length, n_fft=n_fft)[0]

    # Spectral bandwidth (for richness)
    spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, hop_length=hop_length, n_fft=n_fft)[0]

    # Spectral flatness (for richness — flat = noise-like = rich)
    spectral_flatness = librosa.feature.spectral_flatness(y=y, hop_length=hop_length, n_fft=n_fft)[0]

    # STFT for spectral richness
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)

    # HPSS + MFCC deltas for vocal detection
    # Harmonic component isolates tonal content (removes drums/transients)
    S_harmonic, _ = librosa.decompose.hpss(S)
    # MFCCs on harmonic component — vocals have high delta variance (phoneme changes)
    mfcc_harmonic = librosa.feature.mfcc(S=librosa.power_to_db(S_harmonic ** 2), sr=sr, n_mfcc=13)
    mfcc_delta = librosa.feature.delta(mfcc_harmonic)
    # Per-frame vocal score: RMS of MFCC deltas across coefficients (skip c0=energy)
    mfcc_delta_rms = np.sqrt(np.mean(mfcc_delta[1:] ** 2, axis=0))
    # Normalize to 0-1 globally
    mfcc_delta_max = float(np.max(mfcc_delta_rms)) if len(mfcc_delta_rms) > 0 else 1.0
    vocal_score_frames = mfcc_delta_rms / max(mfcc_delta_max, 1e-6)

    # RMS energy (loudness) — per frame
    rms = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop_length)[0]

    # Spectral contrast — peak-to-valley per frequency band, per frame
    # Returns shape (n_bands+1, n_frames), default 7 bands
    spec_contrast = librosa.feature.spectral_contrast(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    # Average across bands for a single per-frame contrast score
    spec_contrast_avg = np.mean(spec_contrast, axis=0)

    # Frame times
    frame_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr, hop_length=hop_length)

    # Global normalization ranges
    flux_min = float(np.min(onset_env))
    flux_max = float(np.max(onset_env))
    centroid_max = float(np.max(spectral_centroid)) if len(spectral_centroid) > 0 else 1.0
    rms_max = float(np.max(rms)) if len(rms) > 0 else 1.0
    contrast_max = float(np.max(spec_contrast_avg)) if len(spec_contrast_avg) > 0 else 1.0
    bandwidth_max = float(np.max(spectral_bandwidth)) if len(spectral_bandwidth) > 0 else 1.0

    # Analyze each section
    sections = []
    for part in song_structure.parts:
        section = _analyze_section(
            part_name=part.name,
            start_time=part.start_time,
            end_time=part.start_time + part.duration,
            onset_env=onset_env,
            onset_times=onset_times,
            spectral_centroid=spectral_centroid,
            spectral_bandwidth=spectral_bandwidth,
            spectral_flatness=spectral_flatness,
            S=S,
            freqs=freqs,
            frame_times=frame_times,
            sr=sr,
            hop_length=hop_length,
            flux_min=flux_min,
            flux_max=flux_max,
            centroid_max=centroid_max,
            bandwidth_max=bandwidth_max,
            vocal_score_frames=vocal_score_frames,
            rms=rms,
            rms_max=rms_max,
            spec_contrast_avg=spec_contrast_avg,
            contrast_max=contrast_max,
        )
        sections.append(section)

    return SongAnalysis(
        sections=sections,
        global_flux_range=(flux_min, flux_max),
        sample_rate=sr,
        duration=duration,
    )


def _analyze_section(
    part_name: str,
    start_time: float,
    end_time: float,
    onset_env: np.ndarray,
    onset_times: np.ndarray,
    spectral_centroid: np.ndarray,
    spectral_bandwidth: np.ndarray,
    spectral_flatness: np.ndarray,
    S: np.ndarray,
    freqs: np.ndarray,
    frame_times: np.ndarray,
    sr: int,
    hop_length: int,
    flux_min: float,
    flux_max: float,
    centroid_max: float,
    bandwidth_max: float,
    vocal_score_frames: np.ndarray = None,
    rms: np.ndarray = None,
    rms_max: float = 1.0,
    spec_contrast_avg: np.ndarray = None,
    contrast_max: float = 1.0,
) -> SectionAnalysis:
    """Analyze a single section of the song."""

    # Get frame indices for this section
    mask = (frame_times >= start_time) & (frame_times < end_time)
    if not np.any(mask):
        return SectionAnalysis(name=part_name, start_time=start_time, end_time=end_time)

    section_frames = np.where(mask)[0]
    section_onset_env = onset_env[section_frames] if len(section_frames) <= len(onset_env) else onset_env[mask[:len(onset_env)]]

    # 1. Spectral flux — normalized average
    flux_range = flux_max - flux_min
    if flux_range > 0 and len(section_onset_env) > 0:
        normalized_flux = (section_onset_env - flux_min) / flux_range
        spectral_flux_avg = float(np.mean(normalized_flux))
        # Subsample envelope to 32 points for matching
        envelope_32 = _resample_to_n(normalized_flux, 32)
    else:
        spectral_flux_avg = 0.0
        envelope_32 = [0.0] * 32

    # 2. Transient sharpness — onset density and strength
    section_onsets = onset_times[(onset_times >= start_time) & (onset_times < end_time)]
    section_duration = end_time - start_time
    if section_duration > 0 and len(section_onsets) > 0:
        onset_density = len(section_onsets) / section_duration  # onsets per second
        # Normalize: ~0-10 onsets/sec mapped to 0-1
        transient_sharpness = min(1.0, onset_density / 10.0)
    else:
        transient_sharpness = 0.0

    # 3. Spectral richness — combination of bandwidth and flatness
    section_bandwidth = spectral_bandwidth[section_frames] if len(section_frames) <= len(spectral_bandwidth) else spectral_bandwidth[mask[:len(spectral_bandwidth)]]
    section_flatness = spectral_flatness[section_frames] if len(section_frames) <= len(spectral_flatness) else spectral_flatness[mask[:len(spectral_flatness)]]

    if len(section_bandwidth) > 0 and bandwidth_max > 0:
        norm_bandwidth = float(np.mean(section_bandwidth)) / bandwidth_max
    else:
        norm_bandwidth = 0.0
    if len(section_flatness) > 0:
        avg_flatness = float(np.mean(section_flatness))
    else:
        avg_flatness = 0.0

    # Richness = weighted combination of bandwidth and flatness
    spectral_richness = min(1.0, 0.6 * norm_bandwidth + 0.4 * avg_flatness)

    # 4. Vocal presence — HPSS + MFCC delta variance (pre-computed per frame)
    if vocal_score_frames is not None and len(section_frames) > 0:
        section_vocal = vocal_score_frames[section_frames] if section_frames[-1] < len(vocal_score_frames) else vocal_score_frames[mask[:len(vocal_score_frames)]]
        vocal_presence = float(np.mean(section_vocal)) if len(section_vocal) > 0 else 0.0
    else:
        vocal_presence = 0.0

    # 5. Spectral centroid average (for color mapping)
    section_centroid = spectral_centroid[section_frames] if len(section_frames) <= len(spectral_centroid) else spectral_centroid[mask[:len(spectral_centroid)]]
    if len(section_centroid) > 0:
        centroid_avg = float(np.mean(section_centroid))
    else:
        centroid_avg = 0.0

    # 6. RMS energy (loudness) — normalized to 0-1
    rms_energy = 0.0
    if rms is not None and len(section_frames) > 0:
        section_rms = rms[section_frames] if section_frames[-1] < len(rms) else rms[mask[:len(rms)]]
        if len(section_rms) > 0 and rms_max > 0:
            rms_energy = float(np.mean(section_rms)) / rms_max

    # 7. Spectral contrast — normalized to 0-1
    spectral_contrast_val = 0.0
    if spec_contrast_avg is not None and len(section_frames) > 0:
        section_contrast = spec_contrast_avg[section_frames] if section_frames[-1] < len(spec_contrast_avg) else spec_contrast_avg[mask[:len(spec_contrast_avg)]]
        if len(section_contrast) > 0 and contrast_max > 0:
            spectral_contrast_val = float(np.mean(section_contrast)) / contrast_max

    return SectionAnalysis(
        name=part_name,
        start_time=start_time,
        end_time=end_time,
        spectral_flux_avg=spectral_flux_avg,
        spectral_flux_envelope=envelope_32,
        transient_sharpness=transient_sharpness,
        spectral_richness=spectral_richness,
        vocal_presence=vocal_presence,
        spectral_centroid_avg=centroid_avg,
        rms_energy=rms_energy,
        spectral_contrast_avg=spectral_contrast_val,
    )


@dataclass
class FrameFeatures:
    """Per-frame audio features, lightly smoothed and downsampled for display.

    All 5 features at continuous resolution (~10-15fps after downsampling),
    giving a smooth energy contour that shows individual hits and builds.
    """
    times: List[float] = field(default_factory=list)
    flux: List[float] = field(default_factory=list)        # normalized onset strength (0-1)
    transient: List[float] = field(default_factory=list)    # per-frame transient sharpness (0-1)
    richness: List[float] = field(default_factory=list)     # spectral richness (0-1)
    vocal: List[float] = field(default_factory=list)        # HPSS+MFCC delta vocal score (0-1)
    centroid: List[float] = field(default_factory=list)     # spectral centroid (0-1 normalized)
    rms: List[float] = field(default_factory=list)          # RMS energy / loudness (0-1)
    contrast: List[float] = field(default_factory=list)     # spectral contrast (0-1)
    sample_rate: int = 22050
    hop_length: int = 512
    duration: float = 0.0
    # Mel spectrogram for inspector display (dB scale, shape: n_mels × n_time_frames)
    mel_spectrogram_db: Optional[np.ndarray] = field(default=None, repr=False)
    mel_frequencies: Optional[np.ndarray] = field(default=None, repr=False)
    mel_times: Optional[np.ndarray] = field(default=None, repr=False)


def compute_frame_features(audio_path: str, max_display_points: int = 800) -> FrameFeatures:
    """Compute all 5 audio features at frame level, lightly smoothed.

    Returns a continuous envelope for flux, transient, richness, vocal,
    and centroid — downsampled to ~10-15fps for display.

    Args:
        audio_path: Path to audio file
        max_display_points: Downsample to this many points for display

    Returns:
        FrameFeatures with all 5 features at continuous resolution
    """
    if not LIBROSA_AVAILABLE:
        raise ImportError("librosa required for audio analysis")
    from scipy.ndimage import uniform_filter1d

    y, sr = librosa.load(audio_path, sr=22050, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)

    hop_length = 512
    n_fft = 2048
    smooth_window = 5  # ~115ms at 43fps — light smoothing, keeps transients

    # ── Onset strength (flux) ──
    onset_env = librosa.onset.onset_strength(y=y, sr=sr, hop_length=hop_length, n_fft=n_fft)
    frame_times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr, hop_length=hop_length)
    n_frames = len(onset_env)

    # Smooth first, then normalize — preserves 0-1 range after smoothing
    smoothed_flux = uniform_filter1d(onset_env.astype(float), smooth_window)
    sf_min, sf_max = float(np.min(smoothed_flux)), float(np.max(smoothed_flux))
    if sf_max > sf_min:
        norm_flux = (smoothed_flux - sf_min) / (sf_max - sf_min)
    else:
        norm_flux = np.zeros(n_frames)

    # ── Transient sharpness (peakiness) ──
    local_avg = uniform_filter1d(onset_env.astype(float), smooth_window)
    transient_raw = np.where(local_avg > 1e-6, onset_env / local_avg, 0.0)
    t_max = float(np.max(transient_raw)) if n_frames > 0 else 1.0
    norm_transient = np.clip(transient_raw / max(t_max, 1e-6), 0.0, 1.0)

    # ── Spectral features (centroid, bandwidth, flatness) ──
    spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr, hop_length=hop_length, n_fft=n_fft)[0]
    spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr, hop_length=hop_length, n_fft=n_fft)[0]
    spectral_flatness = librosa.feature.spectral_flatness(y=y, hop_length=hop_length, n_fft=n_fft)[0]

    # Ensure same length as onset_env (they should be, but guard)
    min_len = min(n_frames, len(spectral_centroid), len(spectral_bandwidth), len(spectral_flatness))

    # ── Richness: bandwidth + flatness — smooth then normalize ──
    bw_max = float(np.max(spectral_bandwidth[:min_len])) if min_len > 0 else 1.0
    norm_bw = spectral_bandwidth[:min_len] / max(bw_max, 1e-6)
    raw_richness = 0.6 * norm_bw + 0.4 * spectral_flatness[:min_len]
    smoothed_richness = uniform_filter1d(raw_richness.astype(float), smooth_window)
    sr_min, sr_max = float(np.min(smoothed_richness)), float(np.max(smoothed_richness))
    if sr_max > sr_min:
        norm_richness = (smoothed_richness - sr_min) / (sr_max - sr_min)
    else:
        norm_richness = np.full(min_len, 0.5)

    # ── Vocal presence: HPSS + MFCC delta variance ──
    S = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop_length))
    S_harmonic, _ = librosa.decompose.hpss(S)
    mfcc_h = librosa.feature.mfcc(S=librosa.power_to_db(S_harmonic ** 2), sr=sr, n_mfcc=13)
    mfcc_d = librosa.feature.delta(mfcc_h)
    # Per-frame vocal score: RMS of MFCC deltas (skip c0=energy)
    mfcc_d_rms = np.sqrt(np.mean(mfcc_d[1:] ** 2, axis=0))
    mfcc_d_max = float(np.max(mfcc_d_rms)) if len(mfcc_d_rms) > 0 else 1.0
    raw_vocal = mfcc_d_rms[:min_len] / max(mfcc_d_max, 1e-6)
    norm_vocal = np.clip(uniform_filter1d(raw_vocal.astype(float), smooth_window * 3), 0.0, 1.0)

    # ── Centroid: smooth then normalize to 0-1 ──
    smoothed_cent = uniform_filter1d(spectral_centroid[:min_len].astype(float), smooth_window)
    sc_min, sc_max = float(np.min(smoothed_cent)), float(np.max(smoothed_cent))
    if sc_max > sc_min:
        norm_cent = (smoothed_cent - sc_min) / (sc_max - sc_min)
    else:
        norm_cent = np.full(min_len, 0.5)

    # ── RMS energy (loudness): smooth then normalize to 0-1 ──
    rms_raw = librosa.feature.rms(y=y, frame_length=n_fft, hop_length=hop_length)[0]
    smoothed_rms = uniform_filter1d(rms_raw[:min_len].astype(float), smooth_window)
    rms_mn, rms_mx = float(np.min(smoothed_rms)), float(np.max(smoothed_rms))
    if rms_mx > rms_mn:
        norm_rms = (smoothed_rms - rms_mn) / (rms_mx - rms_mn)
    else:
        norm_rms = np.full(min_len, 0.5)

    # ── Spectral contrast: smooth then normalize to 0-1 ──
    spec_contrast = librosa.feature.spectral_contrast(y=y, sr=sr, n_fft=n_fft, hop_length=hop_length)
    raw_contrast = np.mean(spec_contrast, axis=0)[:min_len]
    smoothed_contrast = uniform_filter1d(raw_contrast.astype(float), smooth_window)
    ct_mn, ct_mx = float(np.min(smoothed_contrast)), float(np.max(smoothed_contrast))
    if ct_mx > ct_mn:
        norm_contrast = (smoothed_contrast - ct_mn) / (ct_mx - ct_mn)
    else:
        norm_contrast = np.full(min_len, 0.5)

    # ── Downsample all arrays ──
    if min_len > max_display_points:
        indices = np.linspace(0, min_len - 1, max_display_points, dtype=int)
    else:
        indices = np.arange(min_len)

    # ── Mel spectrogram for inspector display ──
    # Downsample time axis to max_display_points for display performance
    n_mels = 128
    mel_spec = librosa.feature.melspectrogram(
        y=y, sr=sr, n_fft=n_fft, hop_length=hop_length, n_mels=n_mels,
    )
    mel_db = librosa.power_to_db(mel_spec, ref=np.max)
    mel_times_full = librosa.frames_to_time(
        np.arange(mel_db.shape[1]), sr=sr, hop_length=hop_length,
    )
    mel_freqs = librosa.mel_frequencies(n_mels=n_mels, fmin=0, fmax=sr / 2)

    # Downsample time axis by picking evenly spaced columns
    n_mel_frames = mel_db.shape[1]
    if n_mel_frames > max_display_points:
        mel_indices = np.linspace(0, n_mel_frames - 1, max_display_points, dtype=int)
        mel_db = mel_db[:, mel_indices]
        mel_times_ds = mel_times_full[mel_indices]
    else:
        mel_times_ds = mel_times_full

    return FrameFeatures(
        times=[float(frame_times[i]) for i in indices],
        flux=[float(norm_flux[i]) for i in indices],
        transient=[float(norm_transient[i]) for i in indices],
        richness=[float(norm_richness[i]) for i in indices],
        vocal=[float(norm_vocal[i]) for i in indices],
        centroid=[float(norm_cent[i]) for i in indices],
        rms=[float(norm_rms[i]) for i in indices],
        contrast=[float(norm_contrast[i]) for i in indices],
        sample_rate=sr,
        hop_length=hop_length,
        duration=duration,
        mel_spectrogram_db=mel_db,
        mel_frequencies=mel_freqs,
        mel_times=mel_times_ds,
    )


def _resample_to_n(data: np.ndarray, n: int) -> List[float]:
    """Resample a 1D array to exactly n points by averaging bins."""
    if len(data) == 0:
        return [0.0] * n
    if len(data) <= n:
        # Pad with last value
        result = list(data) + [float(data[-1])] * (n - len(data))
        return result[:n]

    # Bin and average
    result = []
    bin_size = len(data) / n
    for i in range(n):
        start = int(i * bin_size)
        end = int((i + 1) * bin_size)
        if end > start:
            result.append(float(np.mean(data[start:end])))
        else:
            result.append(float(data[start]))
    return result
