import { describe, expect, it, vi } from 'vitest';
import { OfflineCaptureClient } from '../../engine/offline/captureClient';

const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe('OfflineCaptureClient', () => {
  it('fetches the manifest from the real, audited endpoint path', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ capture_id: 'BLE-IQ-abc' }));
    const client = new OfflineCaptureClient({ baseUrl: 'http://test.local', fetchImpl: fetchImpl as unknown as typeof fetch });

    const manifest = await client.fetchManifest('BLE-IQ-abc');

    expect(fetchImpl).toHaveBeenCalledWith('http://test.local/api/ble/capture/recordings/BLE-IQ-abc', expect.anything());
    expect(manifest).toEqual({ capture_id: 'BLE-IQ-abc' });
  });

  it('throws a descriptive error when the manifest fetch fails', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('not found', { status: 404 }));
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchManifest('missing')).rejects.toThrow(/404/);
  });

  it('requests an I/Q byte range with a correct Range header against the real /iq endpoint', async () => {
    const buffer = new ArrayBuffer(16);
    const fetchImpl = vi.fn().mockResolvedValue(new Response(buffer, { status: 206 }));
    const client = new OfflineCaptureClient({ baseUrl: 'http://test.local', fetchImpl: fetchImpl as unknown as typeof fetch });

    await client.fetchIqByteRange('BLE-IQ-abc', 800, 815);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe('http://test.local/api/ble/capture/recordings/BLE-IQ-abc/iq');
    expect((init as RequestInit).headers).toMatchObject({ Range: 'bytes=800-815' });
  });

  it('accepts a plain 200 response for a range request (server without Range support)', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(new ArrayBuffer(8), { status: 200 }));
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchIqByteRange('cap', 0, 7)).resolves.toBeInstanceOf(ArrayBuffer);
  });

  it('rejects an inverted or negative byte range before ever calling fetch', async () => {
    const fetchImpl = vi.fn();
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchIqByteRange('cap', 10, 5)).rejects.toThrow();
    await expect(client.fetchIqByteRange('cap', -1, 5)).rejects.toThrow();
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it('throws a descriptive error on a real HTTP failure fetching a byte range', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('error', { status: 500 }));
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchIqByteRange('cap', 0, 7)).rejects.toThrow(/500/);
  });

  // A hung fetch that respects AbortSignal (like the real browser fetch)
  // never resolves on its own -- only the signal firing settles it, which
  // is exactly what a stuck connection/proxy/antivirus-scan looks like in
  // practice. Real regression coverage for "stuck at Fetching I/Q chunk
  // forever with zero feedback".
  const hangingFetchImpl = () =>
    vi.fn((_url: string, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener('abort', () => reject(new DOMException('The operation was aborted.', 'AbortError')));
    }));

  it('times out with a clear, actionable error when a chunk fetch hangs instead of waiting forever', async () => {
    const fetchImpl = hangingFetchImpl();
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchIqByteRange('cap', 0, 15, undefined, 50)).rejects.toThrow(/Timed out after/);
  });

  it('propagates a real caller-initiated cancellation as a plain abort, never relabeled as a timeout', async () => {
    const controller = new AbortController();
    const fetchImpl = hangingFetchImpl();
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });

    const promise = client.fetchIqByteRange('cap', 0, 15, controller.signal, 60_000);
    controller.abort();

    await expect(promise).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('lists recent capture manifests from the real, read-only /recordings endpoint', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ captures: [{ capture_id: 'a' }, { capture_id: 'b' }] }));
    const client = new OfflineCaptureClient({ baseUrl: 'http://test.local', fetchImpl: fetchImpl as unknown as typeof fetch });

    const manifests = await client.fetchRecentCaptureManifests();

    expect(fetchImpl).toHaveBeenCalledWith('http://test.local/api/ble/capture/recordings', expect.anything());
    expect(manifests).toEqual([{ capture_id: 'a' }, { capture_id: 'b' }]);
  });

  it('returns an empty list rather than throwing when the response has no captures field', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({}));
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchRecentCaptureManifests()).resolves.toEqual([]);
  });

  it('throws a descriptive error when listing captures fails', async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response('error', { status: 500 }));
    const client = new OfflineCaptureClient({ fetchImpl: fetchImpl as unknown as typeof fetch });
    await expect(client.fetchRecentCaptureManifests()).rejects.toThrow(/500/);
  });
});
