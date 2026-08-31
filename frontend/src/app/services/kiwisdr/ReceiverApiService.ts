import axios from 'axios';
import type { Receiver, ReceiverFilters, ReceiverMapPoint } from '../../../domain/kiwisdr/Receiver';

const baseURL = 'http://localhost:8000';

const paramsFromFilters = (filters?: Partial<ReceiverFilters>) => ({
  q: filters?.q || undefined,
  country: filters?.country || undefined,
  online: filters?.onlineOnly ? true : undefined,
});

export class ReceiverApiService {
  async listReceivers(filters?: Partial<ReceiverFilters>): Promise<Receiver[]> {
    const response = await axios.get(`${baseURL}/api/receivers`, {
      params: paramsFromFilters(filters),
    });
    return response.data.receivers ?? [];
  }

  async getReceiver(id: string): Promise<Receiver> {
    const response = await axios.get(`${baseURL}/api/receivers/${id}`);
    return response.data;
  }

  async getMapPoints(filters?: Partial<ReceiverFilters>): Promise<ReceiverMapPoint[]> {
    const response = await axios.get(`${baseURL}/api/receivers/map`, {
      params: paramsFromFilters(filters),
    });
    return response.data.points ?? [];
  }

  async refreshCatalog(): Promise<{ count: number; refreshed_at: string; notes: string; status?: string; error?: string }> {
    const response = await axios.post(`${baseURL}/api/receivers/refresh`);
    return response.data;
  }

  async checkHealth(id: string): Promise<Record<string, unknown>> {
    const response = await axios.get(`${baseURL}/api/receivers/${id}/health`);
    return response.data;
  }
}
