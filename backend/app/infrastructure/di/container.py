from __future__ import annotations

from dataclasses import dataclass

from app.application.use_cases.create_marker import CreateMarkerUseCase
from app.application.use_cases.create_session import CreateSessionUseCase
from app.application.use_cases.delete_marker import DeleteMarkerUseCase
from app.application.use_cases.get_audio_status import GetAudioStatusUseCase
from app.application.use_cases.get_live_spectrum import GetLiveSpectrumUseCase
from app.application.use_cases.get_live_waterfall import GetLiveWaterfallUseCase
from app.application.use_cases.load_preset import LoadPresetUseCase
from app.application.use_cases.move_marker import MoveMarkerUseCase
from app.application.use_cases.save_preset import SavePresetUseCase
from app.application.use_cases.set_averaging import SetAveragingUseCase
from app.application.use_cases.set_center_frequency import SetCenterFrequencyUseCase
from app.application.use_cases.set_detector_mode import SetDetectorModeUseCase
from app.application.use_cases.set_gain import SetGainUseCase
from app.application.use_cases.set_noise_floor_offset import SetNoiseFloorOffsetUseCase
from app.application.use_cases.set_rbw import SetRBWUseCase
from app.application.use_cases.set_reference_level import SetReferenceLevelUseCase
from app.application.use_cases.set_sample_rate import SetSampleRateUseCase
from app.application.use_cases.set_span import SetSpanUseCase
from app.application.use_cases.set_vbw import SetVBWUseCase
from app.application.use_cases.start_demodulation import StartDemodulationUseCase
from app.application.use_cases.start_device_stream import StartDeviceStreamUseCase
from app.application.use_cases.start_rf_recording import StartRFRecordingUseCase
from app.application.use_cases.stop_demodulation import StopDemodulationUseCase
from app.application.use_cases.stop_device_stream import StopDeviceStreamUseCase
from app.application.use_cases.stop_rf_recording import StopRFRecordingUseCase
from app.config.settings import settings
from app.domain.entities.analyzer_settings import (
    AnalyzerSettings,
    DemodulationSettings,
    DisplaySettings,
    FilterSettings,
    FrequencySettings,
    GainSettings,
    ResolutionSettings,
    TraceSettings,
)
from app.infrastructure.devices.sdr_device_manager import SDRDeviceManager
from app.infrastructure.persistence.repositories.json_preset_repository import JsonPresetRepository
from app.infrastructure.persistence.repositories.json_session_repository import JsonSessionRepository
from app.infrastructure.web.controllers.demodulation_controller import DemodulationController
from app.infrastructure.web.controllers.device_controller import DeviceController
from app.infrastructure.web.controllers.live_demodulation_controller import LiveDemodulationController
from app.infrastructure.web.controllers.marker_controller import MarkerController
from app.infrastructure.web.controllers.modulated_signal_controller import ModulatedSignalController
from app.infrastructure.web.controllers.preset_controller import PresetController
from app.infrastructure.web.controllers.recording_controller import RecordingController
from app.infrastructure.web.controllers.spectrum_controller import SpectrumController


class _StubSpectrumProvider:
    def get_live_spectrum(self, settings_obj):
        raise NotImplementedError("Spectrum provider not wired yet")

    def get_last_spectrum(self):
        return None

    def clear_trace_state(self):
        return None

    def reset_peak_tracking(self):
        return None


class _StubWaterfallProvider:
    def get_live_waterfall_frame(self, settings_obj):
        raise NotImplementedError("Waterfall provider not wired yet")

    def get_last_waterfall_frame(self):
        return None

    def clear_history(self):
        return None

    def get_history_size(self):
        return 0


class _StubRecordingProvider:
    def start_recording(self, request, settings_obj):
        raise NotImplementedError("Recording provider not wired yet")

    def stop_recording(self):
        raise NotImplementedError("Recording provider not wired yet")

    def get_recording_status(self):
        return "idle"

    def get_last_recording_result(self):
        return None

    def list_recordings(self, directory: str):
        return []


class _StubDemodulatorProvider:
    def start_demodulation(self, request, settings_obj):
        raise NotImplementedError("Demodulator provider not wired yet")

    def stop_demodulation(self):
        raise NotImplementedError("Demodulator provider not wired yet")

    def get_demodulation_status(self):
        return "idle"

    def get_last_demodulation_result(self):
        return None


class _RealOnlyDeviceAdapter:
    def start_streaming(self, settings_obj=None):
        raise RuntimeError("Real SDR streaming is handled by GNU Radio helper processes")

    def stop_streaming(self):
        return {"status": "streaming_stopped", "driver": "uhd_gnuradio"}

    def set_center_frequency(self, frequency_hz: float):
        return {"status": "ok", "center_frequency_hz": frequency_hz}

    def set_center_frequency_hz(self, frequency_hz: float):
        return self.set_center_frequency(frequency_hz)

    def set_sample_rate(self, sample_rate_hz: float):
        return {"status": "ok", "sample_rate_hz": sample_rate_hz}

    def set_sample_rate_hz(self, sample_rate_hz: float):
        return self.set_sample_rate(sample_rate_hz)

    def set_gain(self, gain_db: float):
        return {"status": "ok", "gain_db": gain_db}

    def set_gain_db(self, gain_db: float):
        return self.set_gain(gain_db)


@dataclass(slots=True)
class ApplicationContainer:
    analyzer_settings: AnalyzerSettings
    device_manager: SDRDeviceManager

    device_controller: DeviceController
    spectrum_controller: SpectrumController
    marker_controller: MarkerController
    recording_controller: RecordingController
    demodulation_controller: DemodulationController
    live_demodulation_controller: LiveDemodulationController
    modulated_signal_controller: ModulatedSignalController
    preset_controller: PresetController

    create_session_use_case: CreateSessionUseCase

    @classmethod
    def build(cls) -> "ApplicationContainer":
        analyzer_settings = AnalyzerSettings(
            frequency=FrequencySettings(
                center_frequency_hz=settings.default_device.center_frequency_hz,
                span_hz=settings.default_device.span_hz,
                sample_rate_hz=settings.default_device.sample_rate_hz,
            ),
            gain=GainSettings(
                gain_db=settings.default_device.gain_db,
                agc_enabled=settings.default_device.agc_enabled,
            ),
            trace=TraceSettings(
                detector_mode=settings.default_spectrum.detector_mode,
                trace_mode="clear_write",
                averaging_enabled=settings.default_spectrum.averaging_enabled,
                averaging_factor=settings.default_spectrum.averaging_factor,
                smoothing_enabled=settings.default_spectrum.smoothing_enabled,
                smoothing_factor=settings.default_spectrum.smoothing_factor,
                max_hold_enabled=settings.default_spectrum.max_hold_enabled,
                min_hold_enabled=settings.default_spectrum.min_hold_enabled,
            ),
            resolution=ResolutionSettings(
                fft_size=settings.default_spectrum.fft_size,
                fft_window=settings.default_spectrum.fft_window,
                rbw_hz=settings.default_spectrum.rbw_hz,
                vbw_hz=settings.default_spectrum.vbw_hz,
            ),
            display=DisplaySettings(
                reference_level_db=settings.default_spectrum.reference_level_db,
                min_level_db=settings.default_spectrum.min_level_db,
                max_level_db=settings.default_spectrum.max_level_db,
                noise_floor_offset_db=settings.default_spectrum.noise_floor_offset_db,
                waterfall_enabled=settings.default_waterfall.enabled,
                waterfall_history_size=settings.default_waterfall.history_size,
                color_map=settings.default_waterfall.color_map,
            ),
            filters=FilterSettings(),
            demodulation=DemodulationSettings(
                mode=settings.default_demodulation.mode,
                audio_sample_rate_hz=settings.default_demodulation.audio_sample_rate_hz,
                squelch_enabled=settings.default_demodulation.squelch_enabled,
                squelch_threshold_db=settings.default_demodulation.squelch_threshold_db,
            ),
        )

        device_adapter = _RealOnlyDeviceAdapter()
        device_manager = SDRDeviceManager(adapter=device_adapter)

        spectrum_provider = _StubSpectrumProvider()
        waterfall_provider = _StubWaterfallProvider()
        recording_provider = _StubRecordingProvider()
        demodulator_provider = _StubDemodulatorProvider()

        preset_repository = JsonPresetRepository(settings.storage.presets_dir)
        session_repository = JsonSessionRepository(settings.storage.sessions_dir)

        start_device_stream_use_case = StartDeviceStreamUseCase(device_adapter)
        stop_device_stream_use_case = StopDeviceStreamUseCase(device_adapter)
        set_center_frequency_use_case = SetCenterFrequencyUseCase(device_adapter)
        set_sample_rate_use_case = SetSampleRateUseCase(device_adapter)
        set_gain_use_case = SetGainUseCase(device_adapter)

        get_live_spectrum_use_case = GetLiveSpectrumUseCase(spectrum_provider)
        get_live_waterfall_use_case = GetLiveWaterfallUseCase(waterfall_provider)
        set_span_use_case = SetSpanUseCase(device_adapter)
        set_rbw_use_case = SetRBWUseCase()
        set_vbw_use_case = SetVBWUseCase()
        set_noise_floor_offset_use_case = SetNoiseFloorOffsetUseCase()
        set_reference_level_use_case = SetReferenceLevelUseCase()
        set_detector_mode_use_case = SetDetectorModeUseCase()
        set_averaging_use_case = SetAveragingUseCase()

        create_marker_use_case = CreateMarkerUseCase()
        move_marker_use_case = MoveMarkerUseCase()
        delete_marker_use_case = DeleteMarkerUseCase()

        start_rf_recording_use_case = StartRFRecordingUseCase(recording_provider)
        stop_rf_recording_use_case = StopRFRecordingUseCase(recording_provider)

        start_demodulation_use_case = StartDemodulationUseCase(demodulator_provider)
        stop_demodulation_use_case = StopDemodulationUseCase(demodulator_provider)
        get_audio_status_use_case = GetAudioStatusUseCase(demodulator_provider)

        save_preset_use_case = SavePresetUseCase(preset_repository)
        load_preset_use_case = LoadPresetUseCase(preset_repository)
        create_session_use_case = CreateSessionUseCase(session_repository)

        device_controller = DeviceController(
            start_device_stream_use_case=start_device_stream_use_case,
            stop_device_stream_use_case=stop_device_stream_use_case,
            set_center_frequency_use_case=set_center_frequency_use_case,
            set_sample_rate_use_case=set_sample_rate_use_case,
            set_gain_use_case=set_gain_use_case,
            settings=analyzer_settings,
        )

        spectrum_controller = SpectrumController(
            get_live_spectrum_use_case=get_live_spectrum_use_case,
            get_live_waterfall_use_case=get_live_waterfall_use_case,
            set_span_use_case=set_span_use_case,
            set_rbw_use_case=set_rbw_use_case,
            set_vbw_use_case=set_vbw_use_case,
            set_noise_floor_offset_use_case=set_noise_floor_offset_use_case,
            set_reference_level_use_case=set_reference_level_use_case,
            set_detector_mode_use_case=set_detector_mode_use_case,
            set_averaging_use_case=set_averaging_use_case,
            settings=analyzer_settings,
        )

        marker_controller = MarkerController(
            create_marker_use_case=create_marker_use_case,
            move_marker_use_case=move_marker_use_case,
            delete_marker_use_case=delete_marker_use_case,
        )

        recording_controller = RecordingController(
            start_rf_recording_use_case=start_rf_recording_use_case,
            stop_rf_recording_use_case=stop_rf_recording_use_case,
            settings=analyzer_settings,
        )

        demodulation_controller = DemodulationController(
            start_demodulation_use_case=start_demodulation_use_case,
            stop_demodulation_use_case=stop_demodulation_use_case,
            get_audio_status_use_case=get_audio_status_use_case,
            settings=analyzer_settings,
        )
        live_demodulation_controller = LiveDemodulationController(settings=analyzer_settings)
        modulated_signal_controller = ModulatedSignalController(settings=analyzer_settings)

        preset_controller = PresetController(
            save_preset_use_case=save_preset_use_case,
            load_preset_use_case=load_preset_use_case,
            settings=analyzer_settings,
        )

        return cls(
            analyzer_settings=analyzer_settings,
            device_manager=device_manager,
            device_controller=device_controller,
            spectrum_controller=spectrum_controller,
            marker_controller=marker_controller,
            recording_controller=recording_controller,
            demodulation_controller=demodulation_controller,
            live_demodulation_controller=live_demodulation_controller,
            modulated_signal_controller=modulated_signal_controller,
            preset_controller=preset_controller,
            create_session_use_case=create_session_use_case,
        )
