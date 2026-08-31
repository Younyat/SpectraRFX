"""Global constants for Spectrum Lab."""

from __future__ import annotations

# ============================================================================
# Frequency & Span Limits
# ============================================================================
MIN_CENTER_FREQUENCY_HZ = 9_000  # 9 kHz
MAX_CENTER_FREQUENCY_HZ = 6_000_000_000  # 6 GHz
MIN_SPAN_HZ = 1_000  # 1 kHz
MAX_SPAN_HZ = 5_000_000_000  # 5 GHz
MIN_SAMPLE_RATE_HZ = 2_000_000  # 2 MHz
MAX_SAMPLE_RATE_HZ = 250_000_000  # 250 MHz

# ============================================================================
# Gain & Level
# ============================================================================
MIN_GAIN_DB = 0.0
MAX_GAIN_DB = 76.0
MIN_REFERENCE_LEVEL_DB = -140.0
MAX_REFERENCE_LEVEL_DB = 20.0
MIN_NOISE_FLOOR_OFFSET_DB = -100.0
MAX_NOISE_FLOOR_OFFSET_DB = 100.0

# ============================================================================
# FFT & Resolution
# ============================================================================
MIN_FFT_SIZE = 256
MAX_FFT_SIZE = 65536
DEFAULT_FFT_WINDOW = "hann"
VALID_FFT_WINDOWS = ["rectangular", "hann", "hamming", "blackman", "bartlett"]

MIN_RBW_HZ = 100.0
MAX_RBW_HZ = 10_000_000.0
MIN_VBW_HZ = 100.0
MAX_VBW_HZ = 10_000_000.0

# ============================================================================
# Averaging & Smoothing
# ============================================================================
MIN_AVERAGING_FACTOR = 0.01
MAX_AVERAGING_FACTOR = 1.0
DEFAULT_AVERAGING_FACTOR = 0.2

MIN_SMOOTHING_FACTOR = 0.01
MAX_SMOOTHING_FACTOR = 1.0
DEFAULT_SMOOTHING_FACTOR = 0.15

MIN_AVERAGING_COUNT = 1
MAX_AVERAGING_COUNT = 1000

# ============================================================================
# Detector Modes
# ============================================================================
DETECTOR_MODE_SAMPLE = "sample"
DETECTOR_MODE_AVERAGE = "average"
DETECTOR_MODE_PEAK = "peak"
DETECTOR_MODE_MIN = "min"
VALID_DETECTOR_MODES = [
    DETECTOR_MODE_SAMPLE,
    DETECTOR_MODE_AVERAGE,
    DETECTOR_MODE_PEAK,
    DETECTOR_MODE_MIN,
]

# ============================================================================
# Trace Modes
# ============================================================================
TRACE_MODE_CLEAR_WRITE = "clear_write"
TRACE_MODE_NORMAL = "normal"
TRACE_MODE_MAX_HOLD = "max_hold"
TRACE_MODE_MIN_HOLD = "min_hold"
VALID_TRACE_MODES = [
    TRACE_MODE_CLEAR_WRITE,
    TRACE_MODE_NORMAL,
    TRACE_MODE_MAX_HOLD,
    TRACE_MODE_MIN_HOLD,
]

# ============================================================================
# Demodulation Modes
# ============================================================================
DEMODULATION_OFF = "off"
DEMODULATION_AM = "AM"
DEMODULATION_NFM = "NFM"
DEMODULATION_WFM = "WFM"
DEMODULATION_USB = "USB"
DEMODULATION_LSB = "LSB"
DEMODULATION_CW = "CW"
DEMODULATION_IQ = "IQ"
VALID_DEMODULATION_MODES = [
    DEMODULATION_OFF,
    DEMODULATION_AM,
    DEMODULATION_NFM,
    DEMODULATION_WFM,
    DEMODULATION_USB,
    DEMODULATION_LSB,
    DEMODULATION_CW,
    DEMODULATION_IQ,
]

# ============================================================================
# Recording & Audio
# ============================================================================
MIN_RECORDING_DURATION_SEC = 0.1
MAX_RECORDING_DURATION_SEC = 86400.0  # 24 hours
DEFAULT_RECORDING_DURATION_SEC = 10.0

AUDIO_SAMPLE_RATE_8K = 8_000
AUDIO_SAMPLE_RATE_16K = 16_000
AUDIO_SAMPLE_RATE_24K = 24_000
AUDIO_SAMPLE_RATE_48K = 48_000
VALID_AUDIO_SAMPLE_RATES = [
    AUDIO_SAMPLE_RATE_8K,
    AUDIO_SAMPLE_RATE_16K,
    AUDIO_SAMPLE_RATE_24K,
    AUDIO_SAMPLE_RATE_48K,
]

# IQ Recording Formats
IQ_FORMAT_COMPLEX64_FC32_INTERLEAVED = "complex64_fc32_interleaved"
IQ_FORMAT_INT16_INTERLEAVED = "int16_interleaved"
VALID_IQ_FORMATS = [
    IQ_FORMAT_COMPLEX64_FC32_INTERLEAVED,
    IQ_FORMAT_INT16_INTERLEAVED,
]

# Audio Recording Formats
AUDIO_FORMAT_WAV_PCM16_MONO = "wav_pcm16_mono"
AUDIO_FORMAT_WAV_PCM16_STEREO = "wav_pcm16_stereo"
AUDIO_FORMAT_WAV_PCM32_MONO = "wav_pcm32_mono"
VALID_AUDIO_FORMATS = [
    AUDIO_FORMAT_WAV_PCM16_MONO,
    AUDIO_FORMAT_WAV_PCM16_STEREO,
    AUDIO_FORMAT_WAV_PCM32_MONO,
]

# ============================================================================
# Waterfall
# ============================================================================
MIN_WATERFALL_HISTORY_SIZE = 10
MAX_WATERFALL_HISTORY_SIZE = 2000
DEFAULT_WATERFALL_HISTORY_SIZE = 400

WATERFALL_COLORMAP_TURBO = "turbo"
WATERFALL_COLORMAP_VIRIDIS = "viridis"
WATERFALL_COLORMAP_PLASMA = "plasma"
WATERFALL_COLORMAP_INFERNO = "inferno"
VALID_WATERFALL_COLORMAPS = [
    WATERFALL_COLORMAP_TURBO,
    WATERFALL_COLORMAP_VIRIDIS,
    WATERFALL_COLORMAP_PLASMA,
    WATERFALL_COLORMAP_INFERNO,
]

# ============================================================================
# Device Drivers
# ============================================================================
DEVICE_DRIVER_UHD = "uhd"
DEVICE_DRIVER_RTL_SDR = "rtl_sdr"
DEVICE_DRIVER_MOCK = "mock"
VALID_DEVICE_DRIVERS = [
    DEVICE_DRIVER_UHD,
    DEVICE_DRIVER_RTL_SDR,
    DEVICE_DRIVER_MOCK,
]

# ============================================================================
# Filter Types
# ============================================================================
FILTER_TYPE_LOWPASS = "lowpass"
FILTER_TYPE_HIGHPASS = "highpass"
FILTER_TYPE_BANDPASS = "bandpass"
FILTER_TYPE_BANDSTOP = "bandstop"
FILTER_TYPE_NOTCH = "notch"
VALID_FILTER_TYPES = [
    FILTER_TYPE_LOWPASS,
    FILTER_TYPE_HIGHPASS,
    FILTER_TYPE_BANDPASS,
    FILTER_TYPE_BANDSTOP,
    FILTER_TYPE_NOTCH,
]

FILTER_ORDER_MIN = 1
FILTER_ORDER_MAX = 20
FILTER_ORDER_DEFAULT = 4

# ============================================================================
# Measurement
# ============================================================================
MIN_MARKER_FREQUENCY_HZ = MIN_CENTER_FREQUENCY_HZ
MAX_MARKER_FREQUENCY_HZ = MAX_CENTER_FREQUENCY_HZ

MIN_DELTA_MARKER_OFFSET_HZ = -MAX_SPAN_HZ
MAX_DELTA_MARKER_OFFSET_HZ = MAX_SPAN_HZ

# ============================================================================
# Paths & Filenames
# ============================================================================
RECORDINGS_EXTENSION = ".iq"
SESSIONS_EXTENSION = ".session"
PRESETS_EXTENSION = ".preset"

# ============================================================================
# Timeouts
# ============================================================================
DEVICE_STARTUP_TIMEOUT_SEC = 10.0
DEVICE_SHUTDOWN_TIMEOUT_SEC = 5.0
SPECTRUM_UPDATE_TIMEOUT_SEC = 5.0
RECORDING_START_TIMEOUT_SEC = 5.0
RECORDING_STOP_TIMEOUT_SEC = 5.0

# ============================================================================
# Timing
# ============================================================================
SPECTRUM_UPDATE_INTERVAL_MS = 100  # Update every 100ms
WATERFALL_UPDATE_INTERVAL_MS = 200  # Update every 200ms
MARKER_UPDATE_INTERVAL_MS = 50  # Update markers every 50ms

# ============================================================================
# Performance
# ============================================================================
MAX_CONCURRENT_RECORDINGS = 1
MAX_CONCURRENT_DEMODULATIONS = 4
MAX_SPECTRUM_HISTORY_SIZE = 100

# ============================================================================
# Thresholds & Defaults
# ============================================================================
DEFAULT_NOISE_FLOOR_THRESHOLD_DB = -80.0
DEFAULT_PEAK_DETECTION_THRESHOLD_DB = -60.0
DEFAULT_SNR_THRESHOLD_DB = 6.0

# ============================================================================
# SDR Device Defaults (UHD)
# ============================================================================
UHD_DEFAULT_SAMPLE_RATE_HZ = 2_000_000.0
UHD_DEFAULT_CENTER_FREQUENCY_HZ = 1_000_000_000.0  # 1 GHz
UHD_DEFAULT_GAIN_DB = 20.0
UHD_DEFAULT_ANTENNA = "RX2"

# ============================================================================
# RTL-SDR Defaults
# ============================================================================
RTLSDR_DEFAULT_SAMPLE_RATE_HZ = 2_000_000.0
RTLSDR_DEFAULT_CENTER_FREQUENCY_HZ = 100_000_000.0  # 100 MHz
RTLSDR_DEFAULT_GAIN_DB = 25.0

# ============================================================================
# Error Messages
# ============================================================================
ERROR_INVALID_CENTER_FREQUENCY = "Center frequency must be between {} and {} Hz"
ERROR_INVALID_SPAN = "Span must be between {} and {} Hz"
ERROR_INVALID_GAIN = "Gain must be between {} and {} dB"
ERROR_INVALID_SAMPLE_RATE = "Sample rate must be between {} and {} Hz"
ERROR_DEVICE_NOT_FOUND = "Device not found: {}"
ERROR_DEVICE_BUSY = "Device is busy. Another operation is in progress."
ERROR_INVALID_RECORDING_FORMAT = "Invalid recording format: {}"
ERROR_INVALID_DEMODULATION_MODE = "Invalid demodulation mode: {}"

# ============================================================================
# API
# ============================================================================
API_REQUEST_TIMEOUT_SEC = 30.0
API_MAX_BODY_SIZE_MB = 100.0
