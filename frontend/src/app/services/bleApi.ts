import axios from 'axios';
import {claimBleRequest,rejectBleRequest,resolveBleRequest} from '../operations/bleActionTelemetry';

let bleTelemetryInstalled=false;
if(!bleTelemetryInstalled){
 bleTelemetryInstalled=true;
 axios.interceptors.request.use(config=>{(config as typeof config&{__bleOperationId?:string|null}).__bleOperationId=claimBleRequest(config.url);return config});
 axios.interceptors.response.use(response=>{resolveBleRequest((response.config as typeof response.config&{__bleOperationId?:string|null}).__bleOperationId||null,response.status);return response},error=>{const config=error?.config as {__bleOperationId?:string|null}|undefined;rejectBleRequest(config?.__bleOperationId||null,error instanceof Error?error.message:'Error BLE');return Promise.reject(error)});
}

export interface BleDatasetManifest extends Record<string,unknown>{dataset_id:string;version:string;state:string;intended_task:string;maximum_evidence_level:string;examples_included:number;examples_excluded:number;sessions_completed:number;campaigns_planned:number;training_readiness:string;fingerprinting:string}
export interface BleDatasetDetail{manifest:BleDatasetManifest;protocol:Record<string,unknown>;matrix:Record<string,unknown>[];quality:{research_question_display?:string;metrics?:Record<string,unknown>;warnings?:string[];scientific_status?:Record<string,unknown>};split:Record<string,unknown>;examples:Record<string,unknown>[]}

export type BleJobState = 'created' | 'queued' | 'validating_input' | 'starting_worker' | 'running' | 'validating_artifacts' | 'completed' | 'completed_with_diagnostics' | 'cancel_requested' | 'cancelled' | 'failed' | 'timed_out';
export interface BleCapabilities { enabled: boolean; capability_status: string; scientific_status: string; normative_conformance: string; worker_commit: string; gates: Record<string, string | boolean>; available_input_modes: string[]; unavailable_input_modes: string[] }
export interface BleJob { job_id: string; state: BleJobState; input_mode?: string; processing_duration_seconds?: number; result_summary?: Record<string, unknown>; worker?: Record<string, unknown>; error?: { code?: string; message?: string } | null }
export interface BlePacket extends Record<string, unknown> { packet_id?: string; pdu_type?: string; channel_index?: number; crc_valid?: boolean }
export interface BleAdvertisement extends Record<string, unknown> { packet_id?: string; pdu_type?: string; advertiser_address?: string; ad_structures?: unknown[] }
export interface BleAdvertiser extends Record<string, unknown> { address?: string; address_type?: string; packet_count?: number }
export interface BleJobEvent extends Record<string, unknown> { sequence?: number; timestamp_utc?: string; previous_state?: string; new_state?: string; reason?: string }

// Gate 2A.2 -- separate, experimental, NOT the frozen Gate 1B replay pipeline above.
export interface BleGate2a2Status extends Record<string, unknown> {
  available: boolean;
  reason?: string;
  gate?: string;
  gate_2a1_status?: string;
  gate_2a2_status?: string;
  dsp_gate?: string;
  receiver_candidate?: string;
  candidate_frozen?: boolean;
  development_timing_sweep?: { cases?: number; byte_exact?: number; result?: string; holdout_eligible?: boolean };
  residual_failures?: number;
  holdout_b_created?: boolean;
  iq_recovery_validated?: boolean;
  ota_validated?: boolean;
  worker_repository_commit?: string;
  receiver_commit?: string;
  frozen_bitstream_commit?: string;
  disabled_reason?: string;
}
export type BleGate2a2JobState = 'created' | 'queued' | 'starting_worker' | 'running' | 'cancel_requested' | 'completed' | 'cancelled' | 'failed' | 'timed_out';
export interface BleGate2a2Job { job_id: string; state: BleGate2a2JobState; request?: Record<string, unknown>; error?: string | null; updated_at_utc?: string }
export interface BleGate2a2Candidate extends Record<string, unknown> { receiver_trace_id?: number | string; channel_index?: number; estimated_cfo_hz?: number; estimated_timing_phase?: number; winning_timing_hypothesis_id?: string; timing_hypotheses_evaluated?: number; merged_timing_hypothesis_ids?: string[]; detector_score?: number }
export interface BleGate2a2ConfirmedPacket extends Record<string, unknown> { packet_sha256?: string; pdu_type_name?: string; channel_index?: number; crc_valid?: boolean; crc_computed?: number; crc_received?: number; address?: string|null; address_type?: string|null; payload_octets?: string; advertising_data_hex?: string|null; local_name?: string|null; power_dbfs?: number|null; snr_db?: number|null }
export interface BleSdrDevice { device_id: string; driver: string; label: string; serial_masked?: string | null; rx_channels: number; frequency_ranges_hz: { minimum: number; maximum: number }[]; sample_rate_ranges_sps: { minimum: number; maximum: number }[]; bandwidth_ranges_hz: { minimum: number; maximum: number }[]; gain_elements: string[]; antenna_options: string[]; stream_formats?: string[]; clock_sources?: string[]; time_sources?: string[]; available: boolean }
export interface BleCaptureCapabilities { available: boolean; capture_enabled: boolean; capture_and_decode_enabled: false; reason_code?: string; message?: string; devices: BleSdrDevice[]; default_duration_seconds: number; maximum_duration_seconds: number; supported_formats: string[]; ble_channels: Record<string, number> }
export interface BleCaptureJob { capture_id: string; state: 'queued'|'running'|'cancel_requested'|'completed'|'cancelled'|'failed'|'timed_out'; updated_at_utc?: string; error?: string; request?: Record<string, unknown>; capture_complete?: boolean }
export interface BleCaptureRecord extends Record<string, unknown> { capture_id: string; created_at_utc: string; device_driver: string; center_frequency_hz: number; ble_channel?: number; sample_rate_sps: number; bandwidth_hz: number; requested_duration_seconds: number; actual_size_bytes: number; overflow_count: number; capture_complete: boolean; analysis_status: string; experimental_metadata?: Record<string, unknown> }
export interface BleCaptureLive { available: boolean; timestamp_utc?: string; samples_received?: number; bytes_written?: number; stream_overflows?: number; input_discontinuities?: number; average_power_dbfs?: number; peak_power_dbfs?: number; clipping_percentage?: number; frequencies_hz?: number[]; spectrum_dbfs?: number[]; i_preview?: number[]; q_preview?: number[] }
export interface BleRfDiagnostic extends Record<string, unknown> { capture_id:string; capture:Record<string,unknown>; integrity:Record<string,unknown>; power:Record<string,unknown>; clipping:Record<string,unknown>; burst_detection_replay:Record<string,unknown>; psd:Record<string,unknown>; energy_time_series:Record<string,unknown>[]; diagnostic_conclusion:Record<string,unknown> }
export interface BleOfflineReplayCoverage { total_candidate_segments:number; processed_segments:number; failed_segments:number; pending_segments:number; coverage_percentage:number; checkpoint_sequence?:number; last_checkpoint_at?:string|null }
export interface BleOfflineReplay extends Record<string, unknown> { replay_run_id:string; execution_id:string; capture_id:string; iq_sha256:string; execution_status?:string; termination_reason?:string; scientific_completion_status?:'COMPLETE'|'INCOMPLETE'; decision_scope?:'FULL_CAPTURE'|'PROCESSED_SUBSET_ONLY'; resume_available?:boolean; coverage?:BleOfflineReplayCoverage; candidate_funnel:Record<string,unknown>; candidate_rejection_summary:Record<string,unknown>; target_association_results:Record<string,unknown>; decision:Record<string,unknown>; artifacts:Record<string,unknown> }
export interface BleOfflineReplayProgress extends BleOfflineReplayCoverage { decoder_timeout_count?:number; decoder_internal_error_count?:number; worker_restart_count?:number; resume_available?:boolean }
export interface BleOfflineReplayJob extends Record<string, unknown> { capture_id:string; replay_run_id:string; state:string; resumed?:boolean; progress?:BleOfflineReplayProgress; progress_percent?:number; resume_available?:boolean; exit_status?:string; result?:BleOfflineReplay; error?:string }
export interface BleNativeStatus { available: boolean; adapter_type: 'native_ble'; backend: string; scan_supported: boolean; gatt_supported: boolean; scanning: boolean; scan_session_id?: string|null; device_count: number; reason_code?: string; message?: string; diagnostic?: string; last_error?: string|null }
export interface BleHybridSession { session_id:string; state:string; channel:number; duration_seconds:number; capture_id?:string; target_mode?:string; target_address?:string; target_name_at_start?:string; campaign_intent?:string; negative_control_type?:string|null; operator_confirmation?:boolean; negative_control_result?:string; experimental_metadata?:Record<string,unknown>; operational_visibility?:'operator'|'internal_validation'; created_at_utc?:string; steps:Record<string,string>; counters:Record<string,number>; decode_progress?:{processed_segments:number;total_segments:number;crc_valid_packets:number}; live?:{job?:BleCaptureJob;telemetry?:BleCaptureLive}|null; result?:Record<string,unknown>; error?:string }
export interface BleHybridMatch { sdr_observation_id:string; native_observation_id?:string|null; status:string; rule:string; time_difference_ms?:number|null; address_match?:boolean; payload_match?:boolean; manufacturer_data_match?:boolean; candidate_count?:number }
export interface BleHybridEvidence { session_id:string; capture_id?:string; artifacts:Record<string,string|null|undefined> }
export interface BleNegativeControlSummary {declared_condition:string;declared_condition_display:string;ground_truth_source:string;operator_confirmation:boolean;ambient_ble_traffic_recovered:boolean;ambient_crc_valid_packets:number;target_native_observations:number;target_b200_crc_valid_packets:number;target_strong_matches:number;false_target_attributions:number;result:string;basic_control:string;positive_reference_correlation:string;reinforced_control:string;clean_capture:boolean;training_ready:boolean;fingerprinting:string;condition_provenance:string}
export interface BleScientificSummary { session_id:string; question:string; general_result:string; success_criterion:string; evidence_level:string; maximum_observed_evidence_level?:string; association_evidence_status?:string; effective_claim_level?:string; e4_observation_status?:string; e4_dataset_acceptance_status?:string; quality_gate_version?:string; campaign?:Record<string,unknown>; negative_control?:BleNegativeControlSummary; funnel:Record<string,number|null>; counts:Record<string,number>; target:Record<string,unknown>; functional_validation?:Record<string,{status:string;label:string;detail:string}>; acquisition:Record<string,unknown>; decoder:Record<string,unknown>; correlation:Record<string,unknown>; conclusion?:Record<string,unknown>; protocol?:Record<string,unknown>; protocol_manifest?:Record<string,unknown>; terminal_status?:string; acquisition_quality_status?:string; signal_quality_status?:string; ground_truth_status?:string; target_result?:string; protocol_conformance_status?:string; metadata_status?:string; artifact_integrity_status?:string; summary_status?:string; dataset_eligibility_status?:string; final_reason_codes?:string[]; ambiguity_reason_codes?:string[]; artifacts:Record<string,{available:boolean;name?:string;size_bytes?:number;record_count?:number|null;sha256?:string;created_at_utc?:string;path?:string}>; limitations:string[] }
export interface BleNativeMeasurement { measurement_id: string; device_id: string; measurement_type: string; value: number; unit: string; observed_at_utc: string; acquisition_mode: 'advertisement'|'gatt_read'|'gatt_notify'; source_uuid: string; source_raw_hex: string; parser_id: string; parser_version: string; conversion: { endianness: string; signed: boolean; scale: number; offset: number }; quality: { parsed: boolean; crc_available: boolean } }
export interface BleNativeCharacteristic { uuid: string; description?: string; properties: string[]; descriptors: { handle: number; uuid: string; description?: string }[] }
export interface BleNativeService { service_uuid: string; description?: string; known_name?: string|null; characteristics: BleNativeCharacteristic[] }
export interface BleGattDiagnostic { timestamp_utc: string; operation: string; attempt: number; duration_ms: number; cache_mode: string; status: string; exception_class?: string|null; exception_message?: string|null; winrt_code?: number|null; gatt_communication_status?: string|null; protocol_error?: number|null }
export interface BleConnectionJob { connection_job_id:string; device_id:string; status:string; current_stage:string; step:number; total_steps:number; attempt:number; max_attempts:number; elapsed_seconds:number; error?:string|null; result?:BleNativeDevice }
// TI CC2650 SensorTag -- environmental (AA20, humidity+temperature) and IR
// temperature (AA00) sensor sub-state. "available" is set only by the
// connected GATT fingerprint (phase 2); advertising alone never sets it.
export interface TiSensorReading { temperature_c?: number; relative_humidity_percent?: number; object_temperature_c?: number; ambient_temperature_c?: number; observed_at_utc: string; source_raw_hex: string; stale: boolean }
export interface TiSensorState { available: boolean; active: boolean; status?: 'available'|'unavailable'|'starting'|'starting_no_data_yet'|'active'|'disabled'|'disconnected'; data_uuid?: string; config_uuid?: string; period_uuid?: string; last_reading?: TiSensorReading | null }
export interface BleNativeDevice { device_id: string; address: string; address_type: string; local_name?: string|null; rssi_dbm?: number|null; tx_power_dbm?: number|null; manufacturer_data: Record<string,string>; service_data: Record<string,string>; service_uuids: string[]; first_seen_utc: string; last_seen_utc: string; observation_count: number; data_mode: 'ADVERTISEMENT_VALUE'|'GATT_READ'|'GATT_NOTIFY'|'UNKNOWN_FORMAT'; parser_available: boolean; connection: string; native_state?: string; native_status?: string; advertising_seen?: boolean; connection_attempted?: boolean; connection_established?: boolean; gatt_discovery_attempted?: boolean; gatt_discovery_succeeded?: boolean; profile_recognized?: boolean; measurement_available?: boolean; measurements: BleNativeMeasurement[]; gatt_services: BleNativeService[]; gatt_diagnostics?: BleGattDiagnostic[]; profile_id?: string|null; profile_label?: string|null; profile_detection_source?: 'gatt_fingerprint'|null; environmental_sensor?: TiSensorState; ir_temperature_sensor?: TiSensorState }
export interface BleNativeDevice { scan_session_id?:string|null }

// BLE Packet Analysis Lab (Phase 2) -- strictly read-only over the offline
// replay artifacts produced by BleOfflineReplayService (bleApi.ts's
// BleOfflineReplay* types above). Every field carries a provenance tag.
export type BleProvenance = 'B200'|'WINDOWS'|'B200_AND_WINDOWS'|'DERIVED'|'DECLARED_BY_OPERATOR'|'MANUFACTURER_DOCUMENTATION'|'NOT_AVAILABLE';
export interface BleProvenanceField<T> { value: T; source: BleProvenance }
export interface BlePacketLabCaptureRow { capture_id:string; execution_id?:string|null; campaign_id?:string|null; condition_id?:string|null; session_role?:string|null; iq_sha256?:string|null; created_at_utc?:string|null; duration_seconds?:number|null; ble_channel?:number|null; center_frequency_hz?:number|null; sample_rate_sps?:number|null; receiver?:string; actual_samples?:number|null; actual_size_bytes?:number|null; hash_status?:string|null; acquisition_quality:'PASSED'|'FAILED'; target_address?:string|null; replay: { replay_run_id:string; execution_status?:string|null; scientific_completion_status?:string|null; coverage?:Record<string,number>|null; decision?:string|null; dataset_eligibility_status?:string|null; crc_valid_packets?:number|null; unique_crc_valid_packets?:number|null; strong_target_matches?:number|null; conflicting_matches?:number|null } | null }
export interface BlePacketLabCaptureListing { captures: BlePacketLabCaptureRow[]; classification: Record<'LAST_CREATED_CAPTURE'|'LAST_COMPLETED_CAPTURE'|'LAST_FULLY_ANALYZED_CAPTURE'|'LAST_ACCEPTED_CAPTURE', string|null> }
export interface BlePacketLabJob { job_id:string; job_type:string; capture_id:string; replay_run_id?:string|null; state:'queued'|'running'|'cancel_requested'|'completed'|'cancelled'|'failed'; cancellable:boolean; phase?:string|null; phase_progress?:number; overall_progress:number; message?:string|null; analysis_id?:string; result_summary?: Record<string, unknown>; error?:string; started_at:string; updated_at:string }
export interface BlePacketLabAdStructure { structure_index:number; ad_type_hex:string|null; ad_type_name:string; length:number|null; raw_data_hex: BleProvenanceField<string|null>; parser_status:'DECODED'|'RAW_ONLY'|'UNKNOWN_AD_TYPE'; interpreted_value: BleProvenanceField<unknown>|null; manufacturer: { company_id_raw:BleProvenanceField<string|null>; company_id:BleProvenanceField<number|null>; company_name:BleProvenanceField<string|null>; manufacturer_payload_hex:BleProvenanceField<string|null>; manufacturer_parser_status:string; compatibility_note?:string|null } | null }
export interface BlePacketLabPacket {
  packet_id:string; candidate_id:string; is_target:boolean; knowledge_level:string; physical_unit_caveat:string;
  pdu_type: BleProvenanceField<string|null>; crc_valid: BleProvenanceField<boolean>;
  advertiser_address_raw: BleProvenanceField<string|null>; advertiser_address_canonical: BleProvenanceField<string|null>;
  address_type: BleProvenanceField<string|null>; byte_order_conversion:string;
  local_name: BleProvenanceField<string> | null; company_id: BleProvenanceField<number|null>|null; company_name: BleProvenanceField<string|null>|null;
  manufacturer_parser_status?:string|null; service_uuids:string[]; ad_structures: BlePacketLabAdStructure[];
  link_layer: { parser_status:string; base_status:string; preamble_bits: BleProvenanceField<string|null>; access_address_hex: BleProvenanceField<string>; pdu_header_hex: BleProvenanceField<string|null>; pdu_payload_hex: BleProvenanceField<string|null>; crc_received_hex: BleProvenanceField<number|null>; crc_calculated_hex: BleProvenanceField<number|null>; crc_valid: BleProvenanceField<boolean>; header: { pdu_type_raw:BleProvenanceField<number|null>; pdu_type_name:BleProvenanceField<string|null>; tx_add:BleProvenanceField<number|null>; rx_add:BleProvenanceField<number|null>; payload_length:BleProvenanceField<number|null>; header_valid:BleProvenanceField<boolean> }; rf: { power_dbfs:BleProvenanceField<number|null>; snr_db:BleProvenanceField<number|null>; frequency_hz:BleProvenanceField<number|null> } } | null;
  rf_timestamp_utc?:string|null; packet_start_sample?:number|null; pdu_payload_hex: BleProvenanceField<string|null>;
  windows_evidence: { nearest_windows_callback_timestamp: BleProvenanceField<string>|null; time_delta_ms: BleProvenanceField<number>|null; address_match_status?:string|null; temporal_match_status?:string|null; association_strength?:string|null; association_rejection_reason?:string|null };
  windows_match: BleProvenanceField<'WINDOWS_MATCHED'|'WINDOWS_NOT_MATCHED'|'WINDOWS_EVIDENCE_UNAVAILABLE'>;
}
export interface BlePacketLabTransmitter { logical_transmitter_id:string; addresses_observed:string[]; address_types:string[]; local_names:string[]; company_ids:number[]; service_uuids:string[]; packet_count:number; unique_packet_count:number; b200_observations:number; windows_observations:number; corroborated_observations:number; first_seen?:string|null; last_seen?:string|null; is_target:boolean; classification:string; knowledge_level:string }
export interface BlePacketLabWindowsObservation { native_observation_id:string; bluetooth_address:string; bluetooth_address_type:string; local_name?:string|null; rssi_dbm?:number|null; tx_power_dbm?:number|null; manufacturer_data:Record<string,string>; service_data:Record<string,string>; service_uuids:string[]; connectable?:boolean|null; timestamp_callback_utc:string; scanning_mode:'PASSIVE'|'ACTIVE' }
export interface BlePacketLabSensorObservation { measurement_name:string|null; documented_by: BleProvenanceField<string|null>; value_in_advertising: BleProvenanceField<unknown>; value_via_gatt: BleProvenanceField<unknown>; status:'NOT_TRANSMITTED'|'NOT_PARSED'|'NOT_AVAILABLE'; note:string }
export interface BlePacketLabSensorView { transmitter_id:string; sensor_profile_source:string|null; observations: BlePacketLabSensorObservation[] }
export interface BlePacketLabAnalysis { analysis_id:string; capture_id:string; execution_id?:string|null; replay_run_id:string; generated_at_utc:string; source_read_only:true; source_artifact_modified:false; purpose:'BLE_PACKET_ANALYSIS'; diagnostic_only:true; scientific_campaign_member:false; dataset_eligible:false; training_eligible:false; summary: { capture_id:string; execution_id?:string|null; replay_run_id:string; candidates_analyzed?:number|null; crc_valid_packets:number; unique_contents:number; logical_transmitters_found:number; target_address_candidates?:number|null; strong_associations:number; ambiguous_associations?:number|null; scientific_decision?:string|null; dataset_eligibility_status?:string|null }; transmitters: BlePacketLabTransmitter[]; packets: BlePacketLabPacket[]; windows_only_observations: BlePacketLabWindowsObservation[]; sensor_views: BlePacketLabSensorView[] }

const unwrap = <T>(data: T | Record<string, T>): T => {
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const wrapped = data as Record<string, T>;
    return wrapped.items ?? wrapped.packets ?? wrapped.advertisements ?? wrapped.advertisers ?? wrapped.events ?? data as T;
  }
  return data as T;
};

const normalizeHybridPayload = (payload: Record<string, unknown>) => {
  const metadata = { ...((payload.experimental_metadata as Record<string, unknown> | undefined) ?? {}) };
  if (metadata.execution_purpose === 'POSITIVE_PILOT') {
    const protocolManifest = { ...((metadata.protocol_manifest as Record<string, unknown> | undefined) ?? {}) };
    metadata.analysis_enabled = true;
    protocolManifest.analysis_enabled = true;
    metadata.protocol_manifest = protocolManifest;
  }
  return { ...payload, experimental_metadata: metadata };
};

export class BleApiService {
  constructor(private readonly baseURL = 'http://localhost:8000') {}
  async capabilities() { return (await axios.get<BleCapabilities>(`${this.baseURL}/api/ble/capabilities`)).data; }
  async createReplayJob() { return (await axios.post<BleJob>(`${this.baseURL}/api/ble/jobs`, { contract_version: 'ble-job-v1', profile: 'ble_le1m_primary_advertising', input_mode: 'validated_bitstream_replay', source: { type: 'gate1b_fixture', fixture_id: 'gate1b-campaign-001', source_commit: '7b685f7fb0d161be6577d862711456532dcb3528' }, passive_only: true, expected_worker_commit: '7b685f7fb0d161be6577d862711456532dcb3528' })).data; }
  async job(id: string) { return (await axios.get<BleJob>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}`)).data; }
  async cancel(id: string) { return (await axios.post<BleJob>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/cancel`)).data; }
  async retry(id: string) { return (await axios.post<BleJob>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/retry`)).data; }
  async packets(id: string) { return unwrap((await axios.get<BlePacket[]>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/packets`)).data); }
  async advertisements(id: string) { return unwrap((await axios.get<BleAdvertisement[]>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/advertisements`)).data); }
  async advertisers(id: string) { return unwrap((await axios.get<BleAdvertiser[]>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/advertisers`)).data); }
  async resource<T>(id: string, name: 'channels' | 'diagnostics' | 'events' | 'artifacts') { return unwrap((await axios.get<T>(`${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/${name}`)).data); }
  bundleUrl(id: string) { return `${this.baseURL}/api/ble/jobs/${encodeURIComponent(id)}/bundle`; }

  // Gate 2A.2 -- experimental offline IQ analysis, entirely separate from Gate 1B above.
  async gate2a2Status() { return (await axios.get<BleGate2a2Status>(`${this.baseURL}/api/ble/gate2a2/status`)).data; }
  async createGate2a2Job(payload: { iq_file_path: string; channel_index: number; dc_removal?: boolean; channel_filter?: boolean; cfo_correction?: boolean; timing_recovery?: boolean }) {
    return (await axios.post<BleGate2a2Job>(`${this.baseURL}/api/ble/gate2a2/jobs`, payload)).data;
  }
  async gate2a2Job(id: string) { return (await axios.get<BleGate2a2Job>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}`)).data; }
  async cancelGate2a2Job(id: string) { return (await axios.post<BleGate2a2Job>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/cancel`)).data; }
  async gate2a2Candidates(id: string) { const data = (await axios.get<Record<string, BleGate2a2Candidate[]>>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/candidates`)).data; return data.candidates ?? []; }
  async gate2a2ConfirmedPackets(id: string) { const data = (await axios.get<Record<string, BleGate2a2ConfirmedPacket[]>>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/confirmed-packets`)).data; return data['confirmed-packets'] ?? []; }
  async latestHybridPackets() { const sessions=(await axios.get<{sessions:{session_id:string}[]}>(`${this.baseURL}/api/ble/gate2a2/hybrid/sessions`)).data.sessions; if(!sessions.length)return []; return (await axios.get<{packets:BleGate2a2ConfirmedPacket[]}>(`${this.baseURL}/api/ble/gate2a2/hybrid/sessions/${encodeURIComponent(sessions[0].session_id)}/packets`)).data.packets; }
  async startHybrid(payload:Record<string,unknown>) { return (await axios.post<BleHybridSession>(`${this.baseURL}/api/ble/hybrid/sessions`,normalizeHybridPayload(payload))).data; }
  async hybridSession(id:string) { return (await axios.get<BleHybridSession>(`${this.baseURL}/api/ble/hybrid/sessions/${encodeURIComponent(id)}`)).data; }
  async stopHybrid(id:string) { return (await axios.post<BleHybridSession>(`${this.baseURL}/api/ble/hybrid/sessions/${encodeURIComponent(id)}/stop`)).data; }
  async hybridSessions() { return (await axios.get<{sessions:BleHybridSession[]}>(`${this.baseURL}/api/ble/hybrid/sessions`)).data.sessions; }
  async hybridPackets(id:string) { return (await axios.get<{packets:BleGate2a2ConfirmedPacket[]}>(`${this.baseURL}/api/ble/hybrid/sessions/${encodeURIComponent(id)}/packets`)).data.packets; }
  async hybridMatches(id:string) { return (await axios.get<{matches:BleHybridMatch[]}>(`${this.baseURL}/api/ble/hybrid/sessions/${encodeURIComponent(id)}/matches`)).data.matches; }
  async hybridEvidence(id:string) { return (await axios.get<BleHybridEvidence>(`${this.baseURL}/api/ble/hybrid/sessions/${encodeURIComponent(id)}/evidence`)).data; }
  async hybridScientificSummary(id:string) { return (await axios.get<BleScientificSummary>(`${this.baseURL}/api/ble/hybrid/sessions/${encodeURIComponent(id)}/scientific-summary`)).data; }
  async gate2a2Resource<T>(id: string, name: 'semantic-packets' | 'events' | 'rejections' | 'known-limitations' | 'result-summary') { return (await axios.get<T>(`${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/${name}`)).data; }
  gate2a2BundleUrl(id: string) { return `${this.baseURL}/api/ble/gate2a2/jobs/${encodeURIComponent(id)}/bundle`; }

  async captureCapabilities(refresh = false) { return (await axios.get<BleCaptureCapabilities>(`${this.baseURL}/api/ble/capture/devices`, {params: refresh ? {refresh:true} : undefined})).data; }
  async createCapture(payload: Record<string, unknown>) { return (await axios.post<BleCaptureJob>(`${this.baseURL}/api/ble/capture/jobs`, payload)).data; }
  async captureJob(id: string) { return (await axios.get<BleCaptureJob>(`${this.baseURL}/api/ble/capture/jobs/${encodeURIComponent(id)}`)).data; }
  async cancelCapture(id: string) { return (await axios.post<BleCaptureJob>(`${this.baseURL}/api/ble/capture/jobs/${encodeURIComponent(id)}/cancel`)).data; }
  async captureLive(id: string) { return (await axios.get<BleCaptureLive>(`${this.baseURL}/api/ble/capture/jobs/${encodeURIComponent(id)}/live`)).data; }
  async captures() { return (await axios.get<{ captures: BleCaptureRecord[] }>(`${this.baseURL}/api/ble/capture/recordings`)).data.captures; }
  async verifyCapture(id: string) { return (await axios.get<{ data_valid: boolean; metadata_valid: boolean }>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/verify`)).data; }
  async rfDiagnostic(id: string) { return (await axios.get<BleRfDiagnostic>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/rf-diagnostic`)).data; }
  async offlineReplay(id: string, payload: Record<string, unknown>) { return (await axios.post<BleOfflineReplay>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/offline-replay`, payload)).data; }
  async latestOfflineReplay(id: string) { return (await axios.get<BleOfflineReplay>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/offline-replay/latest`)).data; }
  async startOfflineReplayJob(id: string, payload: Record<string, unknown>) { return (await axios.post<BleOfflineReplayJob>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/offline-replay-jobs`, payload)).data; }
  async offlineReplayJob(id: string, replayRunId: string) { return (await axios.get<BleOfflineReplayJob>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/offline-replay-jobs/${encodeURIComponent(replayRunId)}`)).data; }
  async latestOfflineReplayJob(id: string) { return (await axios.get<BleOfflineReplayJob>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/offline-replay-jobs/latest`)).data; }
  async cancelOfflineReplayJob(id: string, replayRunId: string) { return (await axios.post<BleOfflineReplayJob>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/offline-replay-jobs/${encodeURIComponent(replayRunId)}/cancel`)).data; }
  async rfDiagnosticProfiles() { return (await axios.get<Record<string, unknown>>(`${this.baseURL}/api/ble/capture/rf-diagnostic-profiles`)).data; }
  async analyzeCapture(id: string) { return (await axios.post<BleGate2a2Job>(`${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/analyze`)).data; }
  captureMetaUrl(id: string) { return `${this.baseURL}/api/ble/capture/recordings/${encodeURIComponent(id)}/sigmf-meta`; }
  async nativeStatus() { return (await axios.get<BleNativeStatus>(`${this.baseURL}/api/ble/native/status`)).data; }
  async startNativeScan() { return (await axios.post(`${this.baseURL}/api/ble/native/scan/start`)).data; }
  async stopNativeScan() { return (await axios.post(`${this.baseURL}/api/ble/native/scan/stop`)).data; }
  async nativeDevices() { return (await axios.get<{devices:BleNativeDevice[]}>(`${this.baseURL}/api/ble/native/devices`)).data.devices; }
  async nativeDevice(id:string) { return (await axios.get<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}`)).data; }
  async connectNative(id:string) { return (await axios.post<BleConnectionJob>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/connect`)).data; }
  async nativeConnectionJob(id:string) { return (await axios.get<BleConnectionJob>(`${this.baseURL}/api/ble/native/connection-jobs/${encodeURIComponent(id)}`)).data; }
  async cancelNativeConnection(id:string) { return (await axios.post<BleConnectionJob>(`${this.baseURL}/api/ble/native/connection-jobs/${encodeURIComponent(id)}/cancel`)).data; }
  async disconnectNative(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/disconnect`)).data; }
  async nativeServices(id:string) { return (await axios.get<{services:BleNativeService[]}>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/services`)).data.services; }
  async nativeDiagnostics(id:string) { return (await axios.get<Record<string,unknown>>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/gatt-diagnostics`)).data; }
  async readNative(id:string,uuid:string) { return (await axios.post(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/characteristics/${encodeURIComponent(uuid)}/read`)).data; }
  async subscribeNative(id:string,uuid:string) { return (await axios.post(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/characteristics/${encodeURIComponent(uuid)}/subscribe`)).data; }
  async unsubscribeNative(id:string,uuid:string) { return (await axios.post(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/characteristics/${encodeURIComponent(uuid)}/unsubscribe`)).data; }
  async startEnvironmental(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/environmental/start`)).data; }
  async stopEnvironmental(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/environmental/stop`)).data; }
  async startIrTemperature(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/ir-temperature/start`)).data; }
  async stopIrTemperature(id:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/ir-temperature/stop`)).data; }
  async startLegacySensor(id:string,sensor:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/sensors/${encodeURIComponent(sensor)}/start`)).data; }
  async stopLegacySensor(id:string,sensor:string) { return (await axios.post<BleNativeDevice>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/sensors/${encodeURIComponent(sensor)}/stop`)).data; }
  async startSupportedSensors(id:string) { return (await axios.post<{device:BleNativeDevice;active:number;failed:number;results:unknown[]}>(`${this.baseURL}/api/ble/native/devices/${encodeURIComponent(id)}/sensors/start-supported`)).data; }
  async datasetDefinitions(){return (await axios.get<Record<string,unknown>>(`${this.baseURL}/api/ble/dataset-studio/definitions`)).data;}
  async datasets(){return (await axios.get<{datasets:BleDatasetManifest[]}>(`${this.baseURL}/api/ble/dataset-studio/datasets`)).data.datasets;}
  async dataset(id:string,version='1.0.0'){return (await axios.get<BleDatasetDetail>(`${this.baseURL}/api/ble/dataset-studio/datasets/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}`)).data;}
  async freezeDataset(id:string,version:string){return (await axios.post<BleDatasetDetail>(`${this.baseURL}/api/ble/dataset-studio/datasets/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/freeze`)).data;}
  async ingestDataset(id:string,version:string,payload:Record<string,unknown>){return (await axios.post<BleDatasetDetail>(`${this.baseURL}/api/ble/dataset-studio/datasets/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/ingest`,payload)).data;}
  async splitDataset(id:string,version:string,policy:string){return (await axios.post(`${this.baseURL}/api/ble/dataset-studio/datasets/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/split`,{policy})).data;}
  datasetExportUrl(id:string,version:string,kind:string){return `${this.baseURL}/api/ble/dataset-studio/datasets/${encodeURIComponent(id)}/versions/${encodeURIComponent(version)}/export/${encodeURIComponent(kind)}`;}

  // BLE Packet Analysis Lab (Phase 2, read-only over Fase 1 replay artifacts).
  async packetLabCaptures(){return (await axios.get<BlePacketLabCaptureListing>(`${this.baseURL}/api/ble/packet-analysis/captures`)).data;}
  async packetLabLatestCompleted(){return (await axios.get<{classification:string;capture:BlePacketLabCaptureRow}>(`${this.baseURL}/api/ble/packet-analysis/captures/latest-completed`)).data;}
  async packetLabStartJob(captureId:string,replayRunId?:string){return (await axios.post<BlePacketLabJob>(`${this.baseURL}/api/ble/packet-analysis/jobs`,{capture_id:captureId,replay_run_id:replayRunId})).data;}
  async packetLabJob(jobId:string){return (await axios.get<BlePacketLabJob>(`${this.baseURL}/api/ble/packet-analysis/jobs/${encodeURIComponent(jobId)}`)).data;}
  async packetLabCancelJob(jobId:string){return (await axios.post<BlePacketLabJob>(`${this.baseURL}/api/ble/packet-analysis/jobs/${encodeURIComponent(jobId)}/cancel`)).data;}
  async packetLabLatestAnalysis(captureId:string){return (await axios.get<BlePacketLabAnalysis>(`${this.baseURL}/api/ble/packet-analysis/captures/${encodeURIComponent(captureId)}/analysis`)).data;}
}
