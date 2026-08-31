from __future__ import annotations


class PresetController:
    def __init__(self, save_preset_use_case, load_preset_use_case, settings):
        self._save_preset_use_case = save_preset_use_case
        self._load_preset_use_case = load_preset_use_case
        self._settings = settings
        self._presets: dict[str, dict] = {}

    def save_preset(self, name: str, config: dict) -> dict:
        result = self._save_preset_use_case.execute(name, config)
        preset_id = result.get("preset_id")
        if preset_id:
            self._presets[preset_id] = {"preset_id": preset_id, "name": name, "config": config}
        return result

    def load_preset(self, preset_id: str) -> dict:
        if preset_id in self._presets:
            return self._presets[preset_id]
        return self._load_preset_use_case.execute(preset_id)

    def list_presets(self) -> list:
        return list(self._presets.values())
