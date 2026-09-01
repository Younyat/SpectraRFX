// Thin, dependency-free HTTP client for the Storage & Artifact Repository
// Management module's own, entirely new backend routes
// (backend/app/modules/storage_management/routes.py) -- deliberately NOT
// built on ApiService (LIVE-spectrum focused), matching the same isolation
// discipline already established by the AI Research Plugin and RF Terrain
// Offline Reconstruction clients (own client, own base URL, no shared
// state with any other feature).

import type { DeleteItemResult, StorageItemsResponse, StorageSummary } from '../types';

const DEFAULT_BASE_URL = 'http://localhost:8000';

export class StorageManagementApiError extends Error {}

export class StorageManagementClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async parseOrThrow<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const body = await response.text();
      throw new StorageManagementApiError(`HTTP ${response.status}: ${body}`);
    }
    return response.json() as Promise<T>;
  }

  async fetchSummary(): Promise<StorageSummary> {
    const response = await fetch(`${this.baseUrl}/api/storage-management/summary`);
    return this.parseOrThrow<StorageSummary>(response);
  }

  async fetchItems(relativePath: string): Promise<StorageItemsResponse> {
    const url = new URL(`${this.baseUrl}/api/storage-management/items`);
    url.searchParams.set('path', relativePath);
    const response = await fetch(url.toString());
    return this.parseOrThrow<StorageItemsResponse>(response);
  }

  async deleteItem(itemId: string, confirm: boolean): Promise<DeleteItemResult> {
    const response = await fetch(`${this.baseUrl}/api/storage-management/items`, {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ item_id: itemId, confirm }),
    });
    return this.parseOrThrow<DeleteItemResult>(response);
  }
}
