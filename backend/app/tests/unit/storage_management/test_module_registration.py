from __future__ import annotations

from types import SimpleNamespace

import app.modules.storage_management.module as storage_management_module_file
from app.modules.registry import active_backend_modules, backend_modules


def test_module_is_enabled_by_default():
    assert storage_management_module_file.storage_management_module.enabled is True


def test_module_is_included_in_the_real_active_module_list_the_app_uses():
    active_ids = {module.id for module in active_backend_modules()}
    assert "storage_management" in active_ids
    assert any(module.id == "storage_management" for module in backend_modules)


def test_build_router_produces_the_real_documented_routes():
    fake_context = SimpleNamespace(container=SimpleNamespace())
    router = storage_management_module_file._build(context=fake_context)
    paths = {route.path for route in router.routes}
    assert "/storage-management/summary" in paths
    assert "/storage-management/items" in paths
