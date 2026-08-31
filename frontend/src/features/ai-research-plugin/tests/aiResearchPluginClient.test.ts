import { describe, expect, it, vi } from 'vitest';
import { AiResearchPluginApiError, AiResearchPluginClient } from '../api/aiResearchPluginClient';

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

const withMockedFetch = (impl: typeof fetch) => {
  const original = global.fetch;
  global.fetch = impl;
  return () => { global.fetch = original; };
};

describe('AiResearchPluginClient', () => {
  it('imports a model as multipart form data against the real, isolated plugin endpoint', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ model_id: 'AI-MODEL-1' }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new AiResearchPluginClient('http://test.local');

    const file = new File([new Uint8Array([1, 2, 3])], 'toy.onnx');
    await client.importModel(file, 'Toy');

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://test.local/api/ai-research-plugin/models/import');
    expect((init as RequestInit).method).toBe('POST');
    expect((init as RequestInit).body).toBeInstanceOf(FormData);
    restore();
  });

  it('lists models from the real endpoint', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse([{ model_id: 'AI-MODEL-1' }]));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new AiResearchPluginClient('http://test.local');

    const models = await client.listModels();

    expect(fetchImpl).toHaveBeenCalledWith('http://test.local/api/ai-research-plugin/models');
    expect(models).toEqual([{ model_id: 'AI-MODEL-1' }]);
    restore();
  });

  it('sends compatibility and inference requests with the exact real field names the backend expects', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ verdict: 'UNKNOWN', checks: [] }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new AiResearchPluginClient('http://test.local');

    await client.checkCompatibility('AI-MODEL-1', 'BLE-IQ-1', 0.1, 0.2, 'iq_tensor');

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://test.local/api/ai-research-plugin/compatibility');
    const body = JSON.parse((init as RequestInit).body as string);
    expect(body).toEqual({ model_id: 'AI-MODEL-1', capture_id: 'BLE-IQ-1', t0_seconds: 0.1, t1_seconds: 0.2, representation: 'iq_tensor' });
    restore();
  });

  it('throws a descriptive AiResearchPluginApiError on a real HTTP failure, never swallowing it', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('capture not found', { status: 404 }));
    const restore = withMockedFetch(fetchImpl as unknown as typeof fetch);
    const client = new AiResearchPluginClient('http://test.local');

    await expect(client.listModels()).rejects.toBeInstanceOf(AiResearchPluginApiError);
    restore();
  });
});
