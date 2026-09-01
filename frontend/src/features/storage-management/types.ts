// Mirrors backend/app/modules/storage_management/service.py exactly --
// every field here is a real, disclosed value from the filesystem (or, for
// BLE captures, from a real capture_manifest.json), never a frontend
// estimate.

export interface StorageCategory {
  name: string;
  relative_path: string;
  total_bytes: number;
  file_count: number;
  last_modified_utc: string | null;
}

export interface StorageSummary {
  storage_root: string;
  total_bytes: number;
  total_file_count: number;
  categories: StorageCategory[];
}

export type StorageItemKind = 'directory' | 'file' | 'ble_capture' | 'ble_capture_incomplete';

export interface StorageItem {
  item_id: string;
  display_name: string;
  kind: StorageItemKind;
  size_bytes: number;
  file_count: number;
  created_at_utc?: string | null;
  last_modified_utc: string | null;
  preserved: boolean;
  preserved_reason: string;
  extra?: Record<string, unknown>;
}

export interface StorageItemsResponse {
  relative_path: string;
  items: StorageItem[];
}

export interface DeleteItemResult {
  deleted_item_id: string;
  freed_bytes: number;
}
