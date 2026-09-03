from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.modules.ai_research_plugin.contracts import InputRepresentation, ModelFramework, OutputType, RFTask
from app.modules.ai_research_plugin.model_registry import ModelImportError, ModelRegistry
from app.modules.ai_research_plugin.storage import AiPluginStorage
from app.tests.unit.ai_research_plugin.onnx_fixtures import (
    N_CLASSES,
    N_SAMPLES,
    build_invalid_onnx_bytes,
    build_toy_amc_onnx_bytes,
)


@pytest.fixture
def registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(AiPluginStorage(tmp_path / "ai_research_plugin"))


def test_import_extracts_real_shapes_from_the_onnx_graph_into_discovered_fields(registry: ModelRegistry):
    manifest = registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx", model_name="Toy AMC")

    assert manifest.framework == ModelFramework.ONNX
    assert manifest.model_name == "Toy AMC"
    assert manifest.input_discovered.tensor_shape == [1, 2, N_SAMPLES]
    assert manifest.input_discovered.dtype == "float32"
    assert manifest.input_discovered.representation == InputRepresentation.IQ_TENSOR
    assert manifest.output_discovered.tensor_shape == [1, N_CLASSES]
    assert manifest.output_discovered.output_type == OutputType.CLASS_LOGITS
    # Never invented: nothing in the ONNX graph declares a sample rate,
    # task, or class list, so all three stay unset until the operator
    # supplies them.
    assert manifest.input_discovered.sample_rate_hz is None
    assert manifest.output_discovered.classes is None
    assert manifest.task == RFTask.OTHER


def test_import_records_a_real_sha256_of_the_exact_bytes_provided(registry: ModelRegistry):
    model_bytes = build_toy_amc_onnx_bytes()
    manifest = registry.import_onnx_model(model_bytes, "toy_amc.onnx")
    assert manifest.model_sha256 == hashlib.sha256(model_bytes).hexdigest()


def test_import_persists_a_copy_and_the_manifest_is_retrievable(registry: ModelRegistry):
    manifest = registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx")
    fetched = registry.get(manifest.model_id)
    assert fetched is not None
    assert fetched.model_id == manifest.model_id
    assert registry.model_path(manifest).exists()


def test_import_rejects_an_invalid_onnx_file_and_leaves_no_partial_state(registry: ModelRegistry):
    with pytest.raises(ModelImportError):
        registry.import_onnx_model(build_invalid_onnx_bytes(), "bad.onnx")
    assert registry.list_models() == []


def test_apply_overrides_never_touches_the_discovered_fields(registry: ModelRegistry):
    manifest = registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx")
    original_discovered = manifest.input_discovered.model_copy()

    updated = registry.apply_overrides(
        manifest.model_id,
        task=RFTask.MODULATION_CLASSIFICATION,
        input_overrides={"sample_rate_hz": 20_000_000.0},
        output_overrides={"classes": ["BPSK", "QPSK", "8PSK", "16QAM", "64QAM"]},
    )

    assert updated.input_discovered == original_discovered  # untouched
    assert updated.input_overrides.sample_rate_hz == 20_000_000.0
    assert updated.effective_input().sample_rate_hz == 20_000_000.0
    assert updated.effective_output().classes == ["BPSK", "QPSK", "8PSK", "16QAM", "64QAM"]
    assert updated.task == RFTask.MODULATION_CLASSIFICATION


def test_effective_input_prefers_override_over_discovered_when_both_are_set(registry: ModelRegistry):
    manifest = registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx")
    # Discovered dtype is float32 (real, from the graph) -- an operator
    # override must still win for whatever gets USED, without erasing
    # the discovered value.
    updated = registry.apply_overrides(manifest.model_id, input_overrides={"dtype": "float16"})
    assert updated.input_discovered.dtype == "float32"
    assert updated.effective_input().dtype == "float16"


def test_apply_overrides_accepts_signal_bandwidth_and_class_descriptions(registry: ModelRegistry):
    manifest = registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx")

    updated = registry.apply_overrides(
        manifest.model_id,
        input_overrides={"expected_center_frequency_hz": 2_440_000_000.0, "expected_signal_bandwidth_hz": 2_000_000.0},
        output_overrides={
            "classes": ["BPSK", "QPSK"],
            "class_descriptions": {"BPSK": "Binary Phase Shift Keying -- 1 bit/symbol", "QPSK": "Quadrature Phase Shift Keying -- 2 bits/symbol"},
        },
    )

    assert updated.effective_input().expected_signal_bandwidth_hz == 2_000_000.0
    assert updated.effective_output().class_descriptions == {
        "BPSK": "Binary Phase Shift Keying -- 1 bit/symbol",
        "QPSK": "Quadrature Phase Shift Keying -- 2 bits/symbol",
    }


def test_apply_overrides_on_an_unknown_model_id_fails_closed(registry: ModelRegistry):
    with pytest.raises(ModelImportError):
        registry.apply_overrides("AI-MODEL-does-not-exist", task=RFTask.OTHER)


def test_list_models_skips_a_malformed_manifest_without_failing_the_whole_list(tmp_path: Path):
    storage = AiPluginStorage(tmp_path / "ai_research_plugin")
    registry = ModelRegistry(storage)
    registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx")
    (storage.manifests_dir / "corrupt.json").write_text("{not valid json", encoding="utf-8")

    models = registry.list_models()

    assert len(models) == 1


def test_delete_removes_both_the_model_file_and_the_manifest(registry: ModelRegistry):
    manifest = registry.import_onnx_model(build_toy_amc_onnx_bytes(), "toy_amc.onnx")
    model_path = registry.model_path(manifest)
    assert model_path.exists()

    registry.delete(manifest.model_id)

    assert not model_path.exists()
    assert registry.get(manifest.model_id) is None


def test_import_from_folder_imports_every_real_onnx_file_it_finds(registry: ModelRegistry, tmp_path: Path):
    local_folder = tmp_path / "my_local_models"
    local_folder.mkdir()
    (local_folder / "model_a.onnx").write_bytes(build_toy_amc_onnx_bytes(n_samples=64))
    (local_folder / "model_b.onnx").write_bytes(build_toy_amc_onnx_bytes(n_samples=128))
    (local_folder / "notes.txt").write_text("not a model")

    result = registry.import_from_folder(str(local_folder))

    assert len(result.imported) == 2
    assert {m.model_file for m in result.imported} == {"model_a.onnx", "model_b.onnx"}
    assert result.skipped_duplicate == []
    assert result.failed == []
    # Real provenance -- exactly where each file was found, so the UI can
    # separate these from anything imported one file at a time.
    assert all(m.local_source_path is not None and m.local_source_path.endswith(m.model_file) for m in result.imported)
    assert len(registry.list_models()) == 2


def test_import_from_folder_skips_a_model_already_registered_by_content(registry: ModelRegistry, tmp_path: Path):
    already_imported = registry.import_onnx_model(build_toy_amc_onnx_bytes(n_samples=64), "toy_amc.onnx")

    local_folder = tmp_path / "my_local_models"
    local_folder.mkdir()
    # Same real bytes, different filename -- dedupe is by content hash, not name.
    (local_folder / "duplicate_copy.onnx").write_bytes(build_toy_amc_onnx_bytes(n_samples=64))
    (local_folder / "genuinely_new.onnx").write_bytes(build_toy_amc_onnx_bytes(n_samples=128))

    result = registry.import_from_folder(str(local_folder))

    assert result.skipped_duplicate == ["duplicate_copy.onnx"]
    assert [m.model_file for m in result.imported] == ["genuinely_new.onnx"]
    assert len(registry.list_models()) == 2  # already_imported + genuinely_new, duplicate_copy never became a third entry
    assert already_imported.local_source_path is None  # imported one-at-a-time, never retroactively tagged


def test_import_from_folder_reports_an_invalid_onnx_file_without_failing_the_whole_scan(registry: ModelRegistry, tmp_path: Path):
    local_folder = tmp_path / "my_local_models"
    local_folder.mkdir()
    (local_folder / "corrupt.onnx").write_bytes(build_invalid_onnx_bytes())
    (local_folder / "good.onnx").write_bytes(build_toy_amc_onnx_bytes())

    result = registry.import_from_folder(str(local_folder))

    assert [m.model_file for m in result.imported] == ["good.onnx"]
    assert len(result.failed) == 1
    assert result.failed[0].filename == "corrupt.onnx"


def test_import_from_folder_rejects_a_path_that_is_not_a_real_directory(registry: ModelRegistry, tmp_path: Path):
    with pytest.raises(ModelImportError):
        registry.import_from_folder(str(tmp_path / "does_not_exist"))
