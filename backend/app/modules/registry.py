from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI

from app.modules.ai_research_plugin.module import ai_research_plugin_module
from app.modules.capture_lab.module import capture_lab_module
from app.modules.ble_lab.module import ble_lab_module
from app.modules.ble_rffi_studio.module import ble_rffi_studio_module
from app.modules.ble_scientific_results.module import ble_scientific_results_module
from app.modules.demodulation.module import demodulation_module
from app.modules.live_demodulation.module import live_demodulation_module
from app.modules.device.module import device_module
from app.modules.fingerprinting.api_module import fingerprinting_module
from app.modules.kiwisdr.api_module import kiwi_receivers_module, kiwi_sessions_module
from app.modules.markers.module import markers_module
from app.modules.mlops.api_module import mlops_module
from app.modules.presets.module import presets_module
from app.modules.recordings.module import recordings_module
from app.modules.rf_experiment_lab.api_module import rf_experiment_lab_module
from app.modules.e6_oracle_style.api_module import e6_oracle_style_module
from app.modules.rf_intelligence.module import rf_intelligence_module
from app.modules.rf_signal_understanding.module import rf_signal_understanding_module
from app.modules.runtime_settings.module import runtime_settings_module
from app.modules.sessions.module import sessions_module
from app.modules.spectrum.module import spectrum_module
from app.modules.types import BackendModuleDefinition
from app.modules.waterfall.module import waterfall_module


@dataclass(frozen=True)
class BackendModuleContext:
    container: Any
    kiwisdr_module: Any
    fingerprinting_service: Any
    mlops_service: Any


backend_modules: list[BackendModuleDefinition] = [
    device_module,
    runtime_settings_module,
    spectrum_module,
    waterfall_module,
    markers_module,
    recordings_module,
    demodulation_module,
    live_demodulation_module,
    capture_lab_module,
    ble_lab_module,
    ble_rffi_studio_module,
    ble_scientific_results_module,
    fingerprinting_module,
    mlops_module,
    rf_intelligence_module,
    rf_signal_understanding_module,
    rf_experiment_lab_module,
    e6_oracle_style_module,
    kiwi_receivers_module,
    kiwi_sessions_module,
    presets_module,
    sessions_module,
    ai_research_plugin_module,
]


def active_backend_modules() -> list[BackendModuleDefinition]:
    return sorted((module for module in backend_modules if module.enabled), key=lambda module: module.order)


def register_backend_modules(app: FastAPI, context: BackendModuleContext, api_prefix: str) -> None:
    for module in active_backend_modules():
        app.include_router(module.build_router(context), prefix=api_prefix)
