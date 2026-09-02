from __future__ import annotations

from app.modules.ai_research_plugin.catalog.contracts import CatalogEntryKind, CatalogStatus
from app.modules.ai_research_plugin.catalog.seed_catalog import curated_catalog_entries


def test_every_curated_entry_has_a_unique_id():
    entries = curated_catalog_entries()
    ids = [entry.id for entry in entries]
    assert len(ids) == len(set(ids))
    assert len(entries) >= 14


def test_dataset_entries_are_never_presented_as_downloadable_models():
    entries = curated_catalog_entries()
    dataset_entries = [entry for entry in entries if entry.kind == CatalogEntryKind.DATASET]
    assert len(dataset_entries) >= 1
    for entry in dataset_entries:
        assert entry.conversion_status == CatalogStatus.DATASET_ONLY
        assert entry.onnx_available is False


def test_ready_entries_really_have_onnx_available():
    entries = curated_catalog_entries()
    ready_entries = [entry for entry in entries if entry.conversion_status == CatalogStatus.READY]
    # MT-PreamCNN -- directly verified in this session (real file downloaded
    # and imported against the real running backend), and its real
    # [None,1600] declared shape exactly matches this plugin's flat_iq
    # representation. READY is a stricter bar than "the .onnx file loads":
    # it also requires the declared shape to match one of this plugin's
    # implemented representations exactly (see PLATFORM_ADAPTER_REQUIRED).
    # BacalhauNet was downgraded from an earlier, unverified READY claim
    # after direct testing showed its graph uses Brevitas/QONNX custom ops
    # ("Quant") this plugin's onnxruntime does not register. CNN-LSTM OTA
    # was likewise downgraded after direct testing revealed its real
    # declared shape ([8,3,224,224], fixed batch, channels-first) does not
    # match any implemented representation -- it needs a new adapter.
    assert len(ready_entries) >= 1
    for entry in ready_entries:
        assert entry.onnx_available is True


def test_bacalhaunet_is_not_falsely_marked_ready():
    # Regression: this entry was originally (incorrectly) READY. Direct
    # testing against the real downloaded file showed it fails to import
    # (unregistered "Quant" op from Brevitas/QONNX quantization) despite
    # having a real, correctly-shaped rank-3 [1,2,1024] input.
    entries = curated_catalog_entries()
    bacalhaunet = next(entry for entry in entries if entry.id == "CATALOG-BACALHAUNET")
    assert bacalhaunet.conversion_status != CatalogStatus.READY
    assert "Quant" in bacalhaunet.notes


def test_cnn_lstm_ota_is_not_falsely_marked_ready():
    # Regression: this entry was originally (incorrectly) READY with a
    # guessed input_shape of [None,224,224,3]. Direct live testing against
    # the real downloaded file (two independent ONNXRuntimeError messages)
    # showed the real declared shape is a fixed-batch [8,3,224,224], which
    # matches no representation this plugin implements.
    entries = curated_catalog_entries()
    cnn_lstm = next(entry for entry in entries if entry.id == "CATALOG-CNN-LSTM-OTA")
    assert cnn_lstm.conversion_status == CatalogStatus.PLATFORM_ADAPTER_REQUIRED
    assert cnn_lstm.input_shape == [8, 3, 224, 224]


def test_unverified_entry_is_explicitly_flagged_and_never_marked_ready():
    entries = curated_catalog_entries()
    unverified = [entry for entry in entries if entry.independently_verified is False]
    assert len(unverified) >= 1
    for entry in unverified:
        assert entry.conversion_status != CatalogStatus.READY
        assert entry.notes


def test_paper_url_is_always_a_real_url_never_a_citation_string():
    # Regression: paper_url was briefly set to plain citation text (e.g.
    # "IEEE Access 2024") on two entries, which the frontend renders
    # directly as an <a href> -- a real broken-link bug, not just a
    # cosmetic one.
    entries = curated_catalog_entries()
    for entry in entries:
        if entry.paper_url is not None:
            assert entry.paper_url.startswith("http"), entry.id


def test_download_url_when_present_is_a_real_url():
    entries = curated_catalog_entries()
    with_download = [entry for entry in entries if entry.download_url is not None]
    assert len(with_download) >= 8
    for entry in with_download:
        assert entry.download_url.startswith("http"), entry.id


def test_source_url_is_always_a_real_url():
    entries = curated_catalog_entries()
    for entry in entries:
        assert entry.source_url.startswith("http"), entry.id


def test_no_entry_invents_classes_it_does_not_have_evidence_for():
    entries = curated_catalog_entries()
    # A foundation model with no confirmed downstream head must not carry
    # a fabricated class list.
    foundation_entries = [entry for entry in entries if entry.task.value == "FOUNDATION_MODEL"]
    assert len(foundation_entries) >= 2
    for entry in foundation_entries:
        assert entry.classes is None
