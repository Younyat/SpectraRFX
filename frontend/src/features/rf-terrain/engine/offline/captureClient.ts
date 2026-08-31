// Thin, dependency-free HTTP client for the REAL, already-existing,
// read-only capture endpoints (audited before writing this module):
//
//   GET /api/ble/capture/recordings/{capture_id}       -> manifest JSON
//   GET /api/ble/capture/recordings/{capture_id}/iq     -> raw I/Q bytes,
//       Range-capable (Starlette FileResponse, confirmed real)
//
// No new backend endpoint is introduced. Deliberately NOT built on
// ApiService (which is LIVE-spectrum-focused) -- Offline Reconstruction
// stays additive and isolated, matching this module's existing
// architecture ("nothing existing depends on RF Terrain").
// `fetchImpl` is injectable so the chunked-read logic can be unit-tested
// without a real network/backend.
export interface OfflineCaptureClientConfig {
  baseUrl?: string;
  fetchImpl?: typeof fetch;
}

const DEFAULT_BASE_URL = 'http://localhost:8000';

export class OfflineCaptureClient {
  private readonly baseUrl: string;
  private readonly fetchImpl: typeof fetch;

  constructor(config: OfflineCaptureClientConfig = {}) {
    this.baseUrl = config.baseUrl ?? DEFAULT_BASE_URL;
    // The native `fetch` is not a plain function -- it requires `this` to
    // be `window` (or another Window/WorkerGlobalScope) internally.
    // Storing the bare reference and later calling it as
    // `this.fetchImpl(...)` rebinds `this` to the client instance and
    // throws "Failed to execute 'fetch' on 'Window': Illegal invocation".
    // Binding it to globalThis here fixes that for real browser usage
    // while still leaving `fetchImpl` fully injectable for tests.
    this.fetchImpl = config.fetchImpl ?? fetch.bind(globalThis);
  }

  async fetchManifest(captureId: string, signal?: AbortSignal): Promise<unknown> {
    const url = `${this.baseUrl}/api/ble/capture/recordings/${encodeURIComponent(captureId)}`;
    const response = await this.fetchImpl(url, { signal });
    if (!response.ok) {
      throw new Error(`Failed to fetch capture manifest for "${captureId}": HTTP ${response.status}`);
    }
    return response.json();
  }

  // Real, already-existing, read-only endpoint (`GET /recordings`) that
  // lists every completed capture's full manifest, sorted newest-first by
  // `created_at_utc` on the backend -- used to auto-populate a capture
  // picker instead of requiring the operator to already know a capture
  // ID. Returns raw manifest JSON per item; the caller validates each one
  // (same `validateCaptureManifest` used for a single import) rather than
  // trusting this list blindly.
  async fetchRecentCaptureManifests(signal?: AbortSignal): Promise<unknown[]> {
    const url = `${this.baseUrl}/api/ble/capture/recordings`;
    const response = await this.fetchImpl(url, { signal });
    if (!response.ok) {
      throw new Error(`Failed to list captures: HTTP ${response.status}`);
    }
    const body = (await response.json()) as { captures?: unknown };
    return Array.isArray(body.captures) ? body.captures : [];
  }

  // Inclusive byte range, matching HTTP Range semantics exactly (so the
  // caller's byte-offset arithmetic maps 1:1 onto the request).
  async fetchIqByteRange(captureId: string, startByteInclusive: number, endByteInclusive: number, signal?: AbortSignal): Promise<ArrayBuffer> {
    if (startByteInclusive < 0 || endByteInclusive < startByteInclusive) {
      throw new Error(`Invalid byte range [${startByteInclusive}, ${endByteInclusive}]`);
    }
    const url = `${this.baseUrl}/api/ble/capture/recordings/${encodeURIComponent(captureId)}/iq`;
    const response = await this.fetchImpl(url, {
      headers: { Range: `bytes=${startByteInclusive}-${endByteInclusive}` },
      signal,
    });
    // A 200 (full-file response, some servers/proxies strip Range
    // support) is still usable by a caller that only wanted the first
    // range starting at byte 0 -- anything else is a real failure.
    if (response.status !== 206 && response.status !== 200) {
      throw new Error(`Failed to fetch I/Q range [${startByteInclusive}, ${endByteInclusive}] for "${captureId}": HTTP ${response.status}`);
    }
    return response.arrayBuffer();
  }
}
