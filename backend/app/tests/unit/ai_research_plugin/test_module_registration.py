"""Verifies spec section 22/25's central acceptance rule structurally:

    PLATFORM WITHOUT PLUGIN == PLATFORM WITH PLUGIN DISABLED

i.e. with AI_RESEARCH_PLUGIN_ENABLED unset/false (the real default), the
module is excluded from `active_backend_modules()` -- the exact same list
`register_backend_modules()` iterates at real app startup -- so its
router is never built and never mounted, identically to a build of the
platform where this module did not exist at all. And when enabled, the
router really does construct and really does expose the routes described
in routes.py, using onnxruntime/onnx only inside that path.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import app.modules.ai_research_plugin.module as ai_plugin_module_file
from app.modules.registry import active_backend_modules, backend_modules


def test_module_is_disabled_by_default():
    assert ai_plugin_module_file.AI_RESEARCH_PLUGIN_ENABLED is False
    assert ai_plugin_module_file.ai_research_plugin_module.enabled is False


def test_disabled_module_is_excluded_from_the_real_active_module_list_the_app_uses():
    active_ids = {module.id for module in active_backend_modules()}
    assert "ai_research_plugin" not in active_ids

    # Every OTHER real module that is normally active stays active --
    # this module's mere presence in the registry changes nothing else.
    other_enabled_ids = {module.id for module in backend_modules if module.id != "ai_research_plugin" and module.enabled}
    assert other_enabled_ids <= active_ids


def test_enabling_via_env_var_makes_the_module_active(monkeypatch):
    monkeypatch.setenv("AI_RESEARCH_PLUGIN_ENABLED", "true")
    reloaded = importlib.reload(ai_plugin_module_file)
    try:
        assert reloaded.ai_research_plugin_module.enabled is True
    finally:
        # Restore the real default for every other test in this process.
        monkeypatch.delenv("AI_RESEARCH_PLUGIN_ENABLED", raising=False)
        importlib.reload(ai_plugin_module_file)


def test_build_router_when_enabled_produces_the_real_documented_routes():
    # _build() reads context.container.analyzer_settings to wire the LIVE
    # inference bridge -- a lightweight stand-in is enough here since this
    # test only exercises router construction, never an actual live
    # capture.
    fake_context = SimpleNamespace(container=SimpleNamespace(analyzer_settings=object()))
    router = ai_plugin_module_file._build(context=fake_context)
    paths = {route.path for route in router.routes}
    assert "/ai-research-plugin/status" in paths
    assert "/ai-research-plugin/models" in paths
    assert "/ai-research-plugin/models/import" in paths
    assert "/ai-research-plugin/captures" in paths
    assert "/ai-research-plugin/compatibility" in paths
    assert "/ai-research-plugin/inference" in paths
    assert "/ai-research-plugin/inference/live" in paths
