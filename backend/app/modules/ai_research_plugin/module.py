"""Backend module wiring for the AI Model Research Plugin.

`AI_RESEARCH_PLUGIN_ENABLED` defaults to OFF -- spec section 22's
acceptance rule ("ENABLE AI PLUGIN = FALSE -> la aplicacion debe
comportarse exactamente como antes") is enforced structurally, not just
by convention: when disabled, `registry.py`'s `active_backend_modules()`
filters this module out BEFORE `_build()` is ever called (see
app/modules/registry.py), so the router is never constructed and never
mounted. All onnx/onnxruntime imports are deferred to INSIDE `_build()`
(never at this file's top level) specifically so importing this module
during app startup never requires onnx/onnxruntime to even be installed
unless the flag is actually on.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.config.settings import settings
from app.modules.types import BackendModuleDefinition


def _env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}


AI_RESEARCH_PLUGIN_ENABLED = _env_bool("AI_RESEARCH_PLUGIN_ENABLED", False)


def _build(context):
    # Deferred on purpose -- see module docstring.
    from app.infrastructure.sdr.real_spectrum_stream import real_spectrum_stream
    from app.modules.ai_research_plugin.capture_bridge import ReadOnlyCaptureBridge
    from app.modules.ai_research_plugin.inference_service import AiInferenceService
    from app.modules.ai_research_plugin.live_bridge import LiveIqBridge
    from app.modules.ai_research_plugin.model_registry import ModelRegistry
    from app.modules.ai_research_plugin.routes import build_ai_research_plugin_router
    from app.modules.ai_research_plugin.storage import AiPluginStorage
    from app.modules.ble_lab.shared_managers import get_shared_managers

    storage_root: Path = settings.storage.storage_root / "ai_research_plugin"
    storage = AiPluginStorage(storage_root)
    registry = ModelRegistry(storage)

    # Read-only: only ever calls .list_captures()/.metadata()/.data_path()
    # on the SAME manager ble_lab already constructed against the real
    # SDR -- never a second, competing manager (see capture_bridge.py's
    # module docstring). If ble_lab did not initialize one (e.g. it is
    # disabled), the bridge degrades to "no captures available" rather
    # than failing to start.
    shared = get_shared_managers()
    capture_manager = shared.capture_manager if shared else None
    capture_bridge = ReadOnlyCaptureBridge(capture_manager)

    # LIVE inference (additive, opt-in): reuses the SAME real_spectrum_stream
    # singleton and analyzer_settings Live Monitor/RF Terrain already use --
    # never a second SDR session (see live_bridge.py and
    # RealSpectrumStream.capture_live_iq_snapshot). context.container is the
    # real ApplicationContainer built once at app startup (app/main.py), so
    # analyzer_settings here is the exact same shared settings object every
    # other spectrum-facing controller already reads.
    live_bridge = LiveIqBridge(real_spectrum_stream, context.container.analyzer_settings)

    inference_service = AiInferenceService(
        registry=registry, capture_bridge=capture_bridge, storage=storage, live_bridge=live_bridge,
    )
    return build_ai_research_plugin_router(registry, capture_bridge, inference_service)


ai_research_plugin_module = BackendModuleDefinition(
    "ai_research_plugin",
    "AI Model Research Plugin",
    AI_RESEARCH_PLUGIN_ENABLED,
    200,  # high order: registered after ble_lab so get_shared_managers() is already populated
    "Experimental, read-only plugin for importing pretrained ONNX models and running "
    "isolated research inference over preserved RF captures. Disabled by default; "
    "changes nothing about the rest of the platform when off.",
    _build,
)
