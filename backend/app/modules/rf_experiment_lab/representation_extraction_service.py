from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from scipy import signal


class RepresentationExtractionService:
    generator_version = "rf_experiment_lab_representations_v1"

    def raw_iq_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._context(payload)
        windows = self._window_plan(context, payload, preview=True)
        return self._preview_result("raw_iq", context, payload, windows, {"window_count": len(windows)})

    def raw_iq_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        context = self._context(payload)
        windows = self._window_plan(context, payload, preview=False)
        output_dir = self._output_dir(payload, context, "raw_iq")
        artifacts = []
        for index, window in enumerate(windows, start=1):
            iq = self._read_iq_window(context["raw_path"], window["start_sample"], window["num_samples"], context["dtype"])
            segment_id = f"raw_iq_window_{index:06d}"
            data_path = output_dir / f"{segment_id}.npy"
            meta_path = output_dir / f"{segment_id}.json"
            channels = np.stack([iq.real, iq.imag]).astype(np.float32)
            np.save(data_path, channels)
            metadata = self._artifact_metadata(segment_id, "raw_iq", context, payload, window, data_path)
            metadata["normalization"] = payload.get("normalization", "none")
            meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            artifacts.append({"data_path": str(data_path), "metadata_path": str(meta_path), "sha256": metadata["sha256"]})
        return self._export_result("raw_iq", context, payload, windows, artifacts)

    def fft_psd_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._derived_preview("fft_psd", payload, self._compute_fft_psd)

    def fft_psd_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._derived_export("fft_psd", payload, self._compute_fft_psd)

    def spectrogram_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._derived_preview("spectrogram", payload, self._compute_spectrogram)

    def spectrogram_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._derived_export("spectrogram", payload, self._compute_spectrogram)

    def waterfall_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._derived_preview("waterfall", payload, self._compute_waterfall)

    def waterfall_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._derived_export("waterfall", payload, self._compute_waterfall)

    def manifest_export(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata_path = Path(str(payload["metadata_path"]))
        metadata = self._load_metadata(metadata_path)
        raw_path = Path(str(payload.get("iq_path") or payload.get("raw_file") or self._raw_path_from_metadata(metadata)))
        output_dir = Path(str(payload.get("output_dir") or metadata_path.parent / "representations"))
        output_dir.mkdir(parents=True, exist_ok=True)
        artifacts = self._collect_manifest_artifacts(payload, output_dir)
        manifest = {
            "dataset_id": payload.get("dataset_id", "rf_experiment_dataset"),
            "dataset_version": payload.get("dataset_version", metadata.get("dataset_version", "unversioned")),
            "capture_id": metadata.get("capture_id") or metadata_path.stem,
            "raw_file_sha256": self._sha256_file(raw_path) if raw_path.exists() else None,
            "representations": sorted({item["representation_type"] for item in artifacts}),
            "artifact_paths": [item["path"] for item in artifacts],
            "artifact_sha256": {item["path"]: item["sha256"] for item in artifacts},
            "parameters": payload.get("parameters", {}),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generator_version": self.generator_version,
        }
        path = output_dir / "representations_manifest.json"
        path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return {"path": str(path), "manifest": manifest}

    def spectral_feature_source_windows(self, payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        context = self._context(payload)
        return context, self._window_plan(context, payload, preview=bool(payload.get("preview", False)))

    def read_iq_window_for_features(self, context: dict[str, Any], window: dict[str, Any]) -> np.ndarray:
        return self._read_iq_window(context["raw_path"], window["start_sample"], window["num_samples"], context["dtype"])

    def fft_psd_for_features(self, iq: np.ndarray, context: dict[str, Any], payload: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
        return self._compute_fft_psd(iq, context, payload, window)

    def time_frequency_for_features(
        self,
        representation_type: str,
        iq: np.ndarray,
        context: dict[str, Any],
        payload: dict[str, Any],
        window: dict[str, Any],
    ) -> dict[str, Any]:
        if representation_type == "spectrogram":
            return self._compute_spectrogram(iq, context, payload, window)
        if representation_type == "waterfall":
            return self._compute_waterfall(iq, context, payload, window)
        raise ValueError(f"Unsupported E3 representation: {representation_type}")

    def _derived_preview(self, representation_type: str, payload: dict[str, Any], compute_fn) -> dict[str, Any]:
        context = self._context(payload)
        windows = self._window_plan(context, payload, preview=True)
        summaries = []
        for window in windows:
            iq = self._read_iq_window(context["raw_path"], window["start_sample"], window["num_samples"], context["dtype"])
            computed = compute_fn(iq, context, payload, window)
            summaries.append(self._array_summary(computed))
        return self._preview_result(representation_type, context, payload, windows, {"windows": summaries})

    def _derived_export(self, representation_type: str, payload: dict[str, Any], compute_fn) -> dict[str, Any]:
        context = self._context(payload)
        windows = self._window_plan(context, payload, preview=False)
        output_dir = self._output_dir(payload, context, representation_type)
        artifacts = []
        for index, window in enumerate(windows, start=1):
            iq = self._read_iq_window(context["raw_path"], window["start_sample"], window["num_samples"], context["dtype"])
            computed = compute_fn(iq, context, payload, window)
            artifact_id = f"{representation_type}_{index:06d}"
            data_path = output_dir / f"{artifact_id}.npy"
            meta_path = output_dir / f"{artifact_id}.json"
            np.save(data_path, computed["data"])
            metadata = self._artifact_metadata(artifact_id, representation_type, context, payload, window, data_path)
            metadata.update({key: value for key, value in computed.items() if key != "data"})
            meta_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            artifacts.append({"data_path": str(data_path), "metadata_path": str(meta_path), "sha256": metadata["sha256"]})
        return self._export_result(representation_type, context, payload, windows, artifacts)

    def _compute_fft_psd(self, iq: np.ndarray, context: dict[str, Any], payload: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
        n_fft = int(payload.get("n_fft", min(4096, max(1, iq.size))))
        fft = np.fft.fftshift(np.fft.fft(iq, n=n_fft))
        magnitude = np.abs(fft).astype(np.float32)
        freq_axis = np.fft.fftshift(np.fft.fftfreq(n_fft, d=1.0 / context["sample_rate_hz"])) + context["center_frequency_hz"]
        nperseg = int(payload.get("welch_nperseg", min(1024, max(1, iq.size))))
        welch_freq, psd = signal.welch(iq, fs=context["sample_rate_hz"], nperseg=nperseg, return_onesided=False)
        order = np.argsort(welch_freq)
        psd = psd[order].astype(np.float32)
        welch_freq = (welch_freq[order] + context["center_frequency_hz"]).astype(np.float32)
        noise_floor = float(np.percentile(10.0 * np.log10(np.maximum(psd, 1e-20)), 20)) if psd.size else None
        occupied_bw = self._occupied_bandwidth(welch_freq, psd)
        data = np.vstack([freq_axis.astype(np.float32), magnitude]).astype(np.float32)
        return {
            "data": data,
            "shape": list(data.shape),
            "fft_magnitude_shape": list(magnitude.shape),
            "welch_psd_shape": list(psd.shape),
            "frequency_axis_hz_start": float(freq_axis[0]) if freq_axis.size else None,
            "frequency_axis_hz_stop": float(freq_axis[-1]) if freq_axis.size else None,
            "noise_floor_db": noise_floor,
            "occupied_bandwidth_hz": occupied_bw,
            "welch_frequency_axis_hz": [float(value) for value in welch_freq[: min(16, welch_freq.size)]],
        }

    def _compute_spectrogram(self, iq: np.ndarray, context: dict[str, Any], payload: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
        n_fft = min(int(payload.get("n_fft", min(1024, max(1, iq.size)))), max(int(iq.size), 1))
        hop = int(payload.get("hop_length", max(n_fft // 2, 1)))
        hop = max(min(hop, n_fft), 1)
        window_type = str(payload.get("window_type", "hann"))
        noverlap = max(0, n_fft - hop)
        freq, time_axis, zxx = signal.stft(
            iq,
            fs=context["sample_rate_hz"],
            window=window_type,
            nperseg=n_fft,
            noverlap=noverlap,
            nfft=n_fft,
            boundary=None,
            padded=False,
            return_onesided=False,
        )
        order = np.argsort(freq)
        power_db = 20.0 * np.log10(np.maximum(np.abs(zxx[order, :]), 1e-12)).astype(np.float32)
        freq_axis = (freq[order] + context["center_frequency_hz"]).astype(np.float32)
        return {
            "data": power_db,
            "shape": list(power_db.shape),
            "n_fft": n_fft,
            "hop_length": hop,
            "window_type": window_type,
            "power_db": True,
            "frequency_axis_hz_start": float(freq_axis[0]) if freq_axis.size else None,
            "frequency_axis_hz_stop": float(freq_axis[-1]) if freq_axis.size else None,
            "time_axis_s_start": float(time_axis[0] + window["start_time_s"]) if time_axis.size else None,
            "time_axis_s_stop": float(time_axis[-1] + window["start_time_s"]) if time_axis.size else None,
        }

    def _compute_waterfall(self, iq: np.ndarray, context: dict[str, Any], payload: dict[str, Any], window: dict[str, Any]) -> dict[str, Any]:
        spec = self._compute_spectrogram(iq, context, payload, window)
        data = spec["data"].T.astype(np.float32)
        spec["data"] = data
        spec["shape"] = list(data.shape)
        spec["adapter"] = "rf_experiment_lab_stft_waterfall_adapter"
        return spec

    def _context(self, payload: dict[str, Any]) -> dict[str, Any]:
        metadata_path = Path(str(payload["metadata_path"]))
        metadata = self._load_metadata(metadata_path)
        raw_path = Path(str(payload.get("iq_path") or payload.get("raw_file") or self._raw_path_from_metadata(metadata)))
        normalized = self._normalize_metadata(metadata, metadata_path, raw_path)
        validation = self._validate_context(normalized)
        if not validation["valid"]:
            raise ValueError("Representation metadata validation failed: " + ", ".join(validation["missing"]))
        if not raw_path.exists():
            raise FileNotFoundError(f"Raw IQ file not found: {raw_path}")
        normalized["raw_path"] = raw_path
        normalized["metadata"] = metadata
        normalized["metadata_path"] = metadata_path
        normalized["raw_file_sha256"] = self._sha256_file(raw_path)
        normalized["total_samples"] = raw_path.stat().st_size // np.dtype(normalized["dtype"]).itemsize
        normalized["validation"] = validation
        return normalized

    def _normalize_metadata(self, metadata: dict[str, Any], metadata_path: Path, raw_path: Path) -> dict[str, Any]:
        config = metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}
        datatype_raw = metadata.get("datatype") or config.get("sample_dtype") or config.get("file_format") or "complex64"
        dtype = self._dtype(datatype_raw)
        return {
            "capture_id": metadata.get("capture_id") or metadata_path.stem,
            "raw_file": str(raw_path),
            "sample_rate_hz": float(metadata.get("sample_rate_hz") or config.get("sample_rate_hz") or 0.0),
            "center_frequency_hz": float(metadata.get("center_frequency_hz") or config.get("center_frequency_hz") or 0.0),
            "datatype": datatype_raw,
            "dtype": dtype,
        }

    def _validate_context(self, context: dict[str, Any]) -> dict[str, Any]:
        missing = []
        if not context.get("sample_rate_hz"):
            missing.append("sample_rate_hz")
        if not context.get("center_frequency_hz"):
            missing.append("center_frequency_hz")
        if context.get("dtype") is None:
            missing.append("datatype")
        return {"valid": not missing, "missing": missing}

    def _window_plan(self, context: dict[str, Any], payload: dict[str, Any], preview: bool) -> list[dict[str, Any]]:
        size = int(payload.get("window_size_samples", min(65536, max(1, context["total_samples"]))))
        overlap = float(payload.get("overlap", 0.0))
        stride = max(int(size * (1.0 - overlap)), 1)
        max_windows = int(payload.get("max_preview_windows" if preview else "max_export_windows", 1 if preview else 32))
        windows = []
        start = int(payload.get("start_sample", 0))
        while start < context["total_samples"] and len(windows) < max_windows:
            end = min(start + size, context["total_samples"])
            num = end - start
            if num <= 0:
                break
            windows.append(
                {
                    "start_sample": start,
                    "end_sample": end,
                    "num_samples": num,
                    "start_time_s": start / context["sample_rate_hz"],
                    "duration_s": num / context["sample_rate_hz"],
                }
            )
            if end >= context["total_samples"]:
                break
            start += stride
        return windows

    def _read_iq_window(self, raw_path: Path, start_sample: int, num_samples: int, dtype: np.dtype) -> np.ndarray:
        with raw_path.open("rb") as handle:
            handle.seek(start_sample * dtype.itemsize)
            data = np.fromfile(handle, dtype=dtype, count=num_samples)
        return np.asarray(data, dtype=np.complex64)

    def _artifact_metadata(
        self,
        artifact_id: str,
        representation_type: str,
        context: dict[str, Any],
        payload: dict[str, Any],
        window: dict[str, Any],
        data_path: Path,
    ) -> dict[str, Any]:
        return {
            "segment_id": artifact_id,
            "capture_id": context["capture_id"],
            "start_sample": window["start_sample"],
            "end_sample": window["end_sample"],
            "num_samples": window["num_samples"],
            "start_time_s": window["start_time_s"],
            "duration_s": window["duration_s"],
            "sample_rate_hz": context["sample_rate_hz"],
            "center_frequency_hz": context["center_frequency_hz"],
            "dtype": str(context["dtype"]),
            "sha256": self._sha256_file(data_path),
            "raw_file": context["raw_file"],
            "raw_file_sha256": context["raw_file_sha256"],
            "representation_type": representation_type,
            "representation_parameters": self._parameters(payload),
            "source_metadata": str(context["metadata_path"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "generator_version": self.generator_version,
        }

    def _preview_result(
        self,
        representation_type: str,
        context: dict[str, Any],
        payload: dict[str, Any],
        windows: list[dict[str, Any]],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "preview_only": True,
            "training_started": False,
            "representation_type": representation_type,
            "capture_id": context["capture_id"],
            "raw_file": context["raw_file"],
            "raw_file_sha256": context["raw_file_sha256"],
            "validation": context["validation"],
            "window_plan": windows,
            "representation_parameters": self._parameters(payload),
            "summary": summary,
        }

    def _export_result(
        self,
        representation_type: str,
        context: dict[str, Any],
        payload: dict[str, Any],
        windows: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "preview_only": False,
            "training_started": False,
            "representation_type": representation_type,
            "capture_id": context["capture_id"],
            "raw_file": context["raw_file"],
            "raw_file_sha256": context["raw_file_sha256"],
            "validation": context["validation"],
            "window_plan": windows,
            "representation_parameters": self._parameters(payload),
            "artifacts": artifacts,
        }

    def _array_summary(self, computed: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in computed.items() if key != "data"}

    def _output_dir(self, payload: dict[str, Any], context: dict[str, Any], representation_type: str) -> Path:
        base = Path(str(payload.get("output_dir") or Path(context["metadata_path"]).parent / "representations"))
        path = base / representation_type
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _collect_manifest_artifacts(self, payload: dict[str, Any], output_dir: Path) -> list[dict[str, str]]:
        values = payload.get("artifact_paths") or []
        paths: list[Path] = []
        if isinstance(values, list):
            paths.extend(Path(str(item)) for item in values)
        paths.extend(output_dir.glob("**/*.npy"))
        artifacts = []
        for path in sorted({item for item in paths if item.exists() and item.is_file()}):
            artifacts.append(
                {
                    "path": str(path),
                    "sha256": self._sha256_file(path),
                    "representation_type": path.parent.name if path.parent.name else path.stem.split("_")[0],
                }
            )
        return artifacts

    def _occupied_bandwidth(self, freq_axis: np.ndarray, psd: np.ndarray) -> float | None:
        if psd.size == 0 or freq_axis.size == 0:
            return None
        threshold = np.percentile(psd, 80)
        active = freq_axis[psd >= threshold]
        if active.size < 2:
            return None
        return float(np.max(active) - np.min(active))

    def _parameters(self, payload: dict[str, Any]) -> dict[str, Any]:
        keys = [
            "window_size_samples",
            "overlap",
            "start_sample",
            "max_preview_windows",
            "max_export_windows",
            "n_fft",
            "hop_length",
            "window_type",
            "welch_nperseg",
            "normalization",
        ]
        return {key: payload.get(key) for key in keys if key in payload}

    def _raw_path_from_metadata(self, metadata: dict[str, Any]) -> str | None:
        config = metadata.get("capture_config", {}) if isinstance(metadata.get("capture_config"), dict) else {}
        artifacts = metadata.get("artifacts", {}) if isinstance(metadata.get("artifacts"), dict) else {}
        return metadata.get("raw_file") or artifacts.get("iq_file") or config.get("output_path")

    def _load_metadata(self, path: Path) -> dict[str, Any]:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(value, dict):
            raise ValueError("metadata JSON must contain an object")
        return value

    def _dtype(self, datatype: Any) -> np.dtype | None:
        if datatype is None:
            return np.dtype(np.complex64)
        value = str(datatype).lower().strip()
        # Recognize complex64 variants
        if value in {"complex64", "cf32_le", "cfile", ".cfile", "iq", ".iq", "complex", "cf32", "float32"}:
            return np.dtype(np.complex64)
        # Default to complex64 if unrecognized
        return np.dtype(np.complex64)

    def _sha256_file(self, path: Path, chunk_size: int = 1024 * 1024) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(chunk_size), b""):
                digest.update(chunk)
        return digest.hexdigest()
