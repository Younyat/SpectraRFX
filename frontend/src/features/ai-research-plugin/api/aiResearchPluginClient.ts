// Thin, dependency-free HTTP client for the AI Research Plugin's own,
// entirely new backend routes (backend/app/modules/ai_research_plugin/
// routes.py) -- deliberately NOT built on ApiService (LIVE-spectrum
// focused), matching the same isolation discipline RF Terrain's Offline
// Reconstruction already established (own client, own base URL, no
// shared state with any other feature).

import type {
  AiPluginCaptureSummary,
  CompatibilityResult,
  InferenceRecord,
  InputRepresentation,
  RFModelManifest,
  RFTask,
} from '../types';

const DEFAULT_BASE_URL = 'http://localhost:8000';

export interface ManifestOverridePayload {
  task?: RFTask;
  input_overrides?: Record<string, unknown>;
  output_overrides?: Record<string, unknown>;
  preprocessing?: Record<string, unknown>;
  provenance?: Record<string, unknown>;
}

export class AiResearchPluginApiError extends Error {}

export class AiResearchPluginClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async parseOrThrow<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const body = await response.text();
      throw new AiResearchPluginApiError(`HTTP ${response.status}: ${body}`);
    }
    return response.json() as Promise<T>;
  }

  async importModel(file: File, modelName?: string): Promise<RFModelManifest> {
    const formData = new FormData();
    formData.append('file', file);
    if (modelName) formData.append('model_name', modelName);
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/models/import`, { method: 'POST', body: formData });
    return this.parseOrThrow<RFModelManifest>(response);
  }

  async listModels(): Promise<RFModelManifest[]> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/models`);
    return this.parseOrThrow<RFModelManifest[]>(response);
  }

  async updateModel(modelId: string, payload: ManifestOverridePayload): Promise<RFModelManifest> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/models/${encodeURIComponent(modelId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return this.parseOrThrow<RFModelManifest>(response);
  }

  async deleteModel(modelId: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/models/${encodeURIComponent(modelId)}`, { method: 'DELETE' });
    await this.parseOrThrow<unknown>(response);
  }

  async listCaptures(): Promise<AiPluginCaptureSummary[]> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/captures`);
    return this.parseOrThrow<AiPluginCaptureSummary[]>(response);
  }

  async checkCompatibility(
    modelId: string, captureId: string, t0Seconds: number, t1Seconds: number, representation: InputRepresentation,
  ): Promise<CompatibilityResult> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/compatibility`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId, capture_id: captureId, t0_seconds: t0Seconds, t1_seconds: t1Seconds, representation }),
    });
    return this.parseOrThrow<CompatibilityResult>(response);
  }

  async runInference(
    modelId: string, captureId: string, t0Seconds: number, t1Seconds: number, representation: InputRepresentation,
  ): Promise<InferenceRecord> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/inference`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId, capture_id: captureId, t0_seconds: t0Seconds, t1_seconds: t1Seconds, representation }),
    });
    return this.parseOrThrow<InferenceRecord>(response);
  }

  async runInferenceLive(modelId: string, representation: InputRepresentation): Promise<InferenceRecord> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/inference/live`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: modelId, representation }),
    });
    return this.parseOrThrow<InferenceRecord>(response);
  }

  async listInferenceRecords(): Promise<InferenceRecord[]> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/inference`);
    return this.parseOrThrow<InferenceRecord[]>(response);
  }

  async getStatus(): Promise<{ enabled: boolean; capture_bridge_available: boolean; live_inference_available: boolean }> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/status`);
    return this.parseOrThrow(response);
  }
}
