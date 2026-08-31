export interface Receiver {
  id: string;
  name: string;
  host: string;
  port: number;
  url: string;
  lat: number | null;
  lon: number | null;
  country: string;
  city: string;
  locator: string;
  is_online: boolean;
  is_public: boolean;
  current_users: number | null;
  max_users: number | null;
  snr: number | null;
  frequency_min_khz: number;
  frequency_max_khz: number;
  last_seen: string;
  source: string;
  notes: string;
  gps_locked?: boolean | null;
  tdoa_available?: boolean | null;
  antenna?: string;
  owner?: string;
  receiver_type?: string;
  latency_ms?: number | null;
  health_status?: string;
}

export interface ReceiverMapPoint {
  id: string;
  name: string;
  host: string;
  port: number;
  url: string;
  lat: number;
  lon: number;
  country: string;
  city: string;
  is_online: boolean;
  current_users: number | null;
  max_users: number | null;
  snr: number | null;
  frequency_min_khz: number;
  frequency_max_khz: number;
  health_status: string;
}

export interface ReceiverFilters {
  q: string;
  country: string;
  onlineOnly: boolean;
}

export interface KiwiSession {
  session_id: string;
  receiver_id: string;
  host: string;
  port: number;
  status: string;
  sample_rate: number;
  mode: string;
  frequency_khz: number;
  compression: boolean;
  agc: boolean;
  created_at: string;
  notes: string[];
}
