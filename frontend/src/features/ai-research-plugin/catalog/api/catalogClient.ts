// Thin, dependency-free HTTP client for the RF Model Discovery Catalog's
// own routes (backend/app/modules/ai_research_plugin/catalog/, mounted
// under the existing /ai-research-plugin router). Deliberately separate
// from AiResearchPluginClient: this client only ever reads catalog data
// (curated + live Hugging Face search) -- it never imports, deletes, or
// runs inference against anything.

import type { CatalogFilters, CatalogListResponse, RFModelCatalogEntry } from '../types';

const DEFAULT_BASE_URL = 'http://localhost:8000';

export class CatalogApiError extends Error {}

export class ModelCatalogClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string = DEFAULT_BASE_URL) {
    this.baseUrl = baseUrl;
  }

  private async parseOrThrow<T>(response: Response): Promise<T> {
    if (!response.ok) {
      const body = await response.text();
      throw new CatalogApiError(`HTTP ${response.status}: ${body}`);
    }
    return response.json() as Promise<T>;
  }

  async listCurated(filters: CatalogFilters = {}): Promise<CatalogListResponse> {
    const url = new URL(`${this.baseUrl}/api/ai-research-plugin/catalog`);
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') url.searchParams.set(key, String(value));
    });
    const response = await fetch(url.toString());
    return this.parseOrThrow<CatalogListResponse>(response);
  }

  async getEntry(entryId: string): Promise<RFModelCatalogEntry> {
    const response = await fetch(`${this.baseUrl}/api/ai-research-plugin/catalog/${encodeURIComponent(entryId)}`);
    return this.parseOrThrow<RFModelCatalogEntry>(response);
  }

  async searchHuggingFace(query: string, limit = 20): Promise<CatalogListResponse> {
    const url = new URL(`${this.baseUrl}/api/ai-research-plugin/catalog/search/huggingface`);
    url.searchParams.set('q', query);
    url.searchParams.set('limit', String(limit));
    const response = await fetch(url.toString());
    return this.parseOrThrow<CatalogListResponse>(response);
  }
}
