import { describe, expect, it, vi } from 'vitest';
import { CatalogApiError, ModelCatalogClient } from '../api/catalogClient';

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const withMockedFetch = (impl: typeof fetch) => {
  const original = global.fetch;
  global.fetch = impl;
  return () => { global.fetch = original; };
};

describe('ModelCatalogClient', () => {
  it('lists the curated catalog from the real, isolated catalog endpoint', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ entries: [{ id: 'CATALOG-X' }], total: 1 }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new ModelCatalogClient('http://test.local');

    const result = await client.listCurated();

    expect(fetchImpl).toHaveBeenCalledWith('http://test.local/api/ai-research-plugin/catalog');
    expect(result.total).toBe(1);
    restore();
  });

  it('serializes filters as query params, omitting undefined ones', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ entries: [], total: 0 }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new ModelCatalogClient('http://test.local');

    await client.listCurated({ task: 'RF_FINGERPRINTING', onnx_available: true });

    const [url] = fetchImpl.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.searchParams.get('task')).toBe('RF_FINGERPRINTING');
    expect(parsed.searchParams.get('onnx_available')).toBe('true');
    expect(parsed.searchParams.has('kind')).toBe(false);
    restore();
  });

  it('fetches a single catalog entry by id', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ id: 'CATALOG-MT-PREAMCNN' }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new ModelCatalogClient('http://test.local');

    await client.getEntry('CATALOG-MT-PREAMCNN');

    expect(fetchImpl).toHaveBeenCalledWith('http://test.local/api/ai-research-plugin/catalog/CATALOG-MT-PREAMCNN');
    restore();
  });

  it('searches Hugging Face with the query and limit as params', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ entries: [], total: 0 }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new ModelCatalogClient('http://test.local');

    await client.searchHuggingFace('rf fingerprint', 5);

    const [url] = fetchImpl.mock.calls[0];
    const parsed = new URL(url as string);
    expect(parsed.pathname).toBe('/api/ai-research-plugin/catalog/search/huggingface');
    expect(parsed.searchParams.get('q')).toBe('rf fingerprint');
    expect(parsed.searchParams.get('limit')).toBe('5');
    restore();
  });

  it('throws a descriptive error on a real HTTP failure', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('bad gateway', { status: 502 }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new ModelCatalogClient('http://test.local');

    await expect(client.searchHuggingFace('x')).rejects.toThrow(CatalogApiError);
    restore();
  });
});
