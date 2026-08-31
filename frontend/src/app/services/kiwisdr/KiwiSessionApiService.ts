import axios from 'axios';
import type { KiwiSession } from '../../../domain/kiwisdr/Receiver';

const baseURL = 'http://localhost:8000';

export class KiwiSessionApiService {
  async createSession(request: {
    receiver_id: string;
    frequency_khz: number;
    mode: string;
    compression: boolean;
    agc: boolean;
  }): Promise<KiwiSession> {
    const response = await axios.post(`${baseURL}/api/kiwi/sessions`, request);
    return response.data;
  }
}
