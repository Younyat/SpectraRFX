import { describe, expect, it, vi } from 'vitest';
import { StorageManagementApiError, StorageManagementClient } from '../api/storageManagementClient';

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const withMockedFetch = (impl: typeof fetch) => {
  const original = global.fetch;
  global.fetch = impl;
  return () => { global.fetch = original; };
};

describe('StorageManagementClient', () => {
  it('fetches the real summary from the real, isolated storage-management endpoint', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ storage_root: 'x', total_bytes: 10, total_file_count: 1, categories: [] }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new StorageManagementClient('http://test.local');

    const summary = await client.fetchSummary();

    expect(fetchImpl).toHaveBeenCalledWith('http://test.local/api/storage-management/summary');
    expect(summary.total_bytes).toBe(10);
    restore();
  });

  it('fetches items for a given category path with the path as a query param', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ relative_path: 'mlops', items: [] }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new StorageManagementClient('http://test.local');

    await client.fetchItems('mlops');

    const [url] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://test.local/api/storage-management/items?path=mlops');
    restore();
  });

  it('sends a DELETE request with the exact real field names the backend expects', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ deleted_item_id: 'mlops/bundle', freed_bytes: 10 }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new StorageManagementClient('http://test.local');

    const result = await client.deleteItem('mlops/bundle', true);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://test.local/api/storage-management/items');
    expect((init as RequestInit).method).toBe('DELETE');
    expect(JSON.parse((init as RequestInit).body as string)).toEqual({ item_id: 'mlops/bundle', confirm: true });
    expect(result).toEqual({ deleted_item_id: 'mlops/bundle', freed_bytes: 10 });
    restore();
  });

  it('throws a descriptive error on a real HTTP failure', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('nope', { status: 400 }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new StorageManagementClient('http://test.local');

    await expect(client.deleteItem('mlops/bundle', false)).rejects.toThrow(StorageManagementApiError);
    restore();
  });
});
