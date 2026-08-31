export type RFProfile = {
  key: string;
  label: string;
  family: string;
  signal_type: string;
  center_frequency_hz: number;
  marker_left_hz: number;
  marker_right_hz: number;
  span_hz: number;
  sample_rate_hz: number;
  expected_bandwidth_hz: number[];
  modulation: string[];
  temporal_pattern: string;
  capture_duration_seconds: number;
  recommended_gain_db: number;
  training_note: string;
};

export type AppliedRFProfile = {
  selected_profile_key: string;
  center_frequency_hz: number;
  start_frequency_hz: number;
  stop_frequency_hz: number;
  span_hz: number;
  sample_rate_hz: number;
  marker_left_hz: number;
  marker_right_hz: number;
  markers: Array<{ id: string; label: string; frequency_hz: number; type: string }>;
  signal_type: string;
  family: string;
  modulation: string[];
  temporal_pattern: string;
  expected_bandwidth_hz: number[];
  capture_duration_seconds: number;
  recommended_gain_db: number;
  training_note: string;
};

export const RF_PROFILE_STORAGE_KEY = 'spectrum-lab-selected-rf-profile';

const WIFI_5GHZ_CHANNELS = [
  36, 40, 44, 48,
  52, 56, 60, 64,
  100, 104, 108, 112, 116, 120, 124, 128,
  132, 136, 140, 144,
  149, 153, 157, 161, 165,
];

const WIFI_5GHZ_PROFILES = Object.fromEntries(
  WIFI_5GHZ_CHANNELS.map((channel) => {
    const center_frequency_hz = (5000 + channel * 5) * 1_000_000;
    const key = `wifi_5g_ch${channel}`;
    return [
      key,
      {
        key,
        label: `Wi-Fi 5 GHz Channel ${channel}`,
        family: 'wifi_80211',
        signal_type: 'wifi_5ghz_ofdm',
        center_frequency_hz,
        marker_left_hz: center_frequency_hz - 10_000_000,
        marker_right_hz: center_frequency_hz + 10_000_000,
        span_hz: 30_000_000,
        sample_rate_hz: 30_000_000,
        expected_bandwidth_hz: [20_000_000],
        modulation: ['OFDM'],
        temporal_pattern: 'bursty_frames',
        capture_duration_seconds: 10,
        recommended_gain_db: 20,
        training_note: `Use for Wi-Fi 5 GHz channel ${channel}. Keep channel width, traffic generation, distance and SDR settings stable across captures.`,
      },
    ];
  }),
) as Record<string, RFProfile>;




const PMR446_ANALOG_CHANNELS = Array.from({ length: 16 }, (_, index) => {
  const channel = index + 1;
  const center_frequency_hz = 446_006_250 + index * 12_500;
  const key = `pmr446_analog_ch${channel}`;

  return [
    key,
    {
      key,
      label: `PMR446 Analog Channel ${channel}`,
      family: 'pmr446_walkie_talkie',
      signal_type: 'pmr446_analog_nfm_voice',
      center_frequency_hz,
      marker_left_hz: center_frequency_hz - 6_250,
      marker_right_hz: center_frequency_hz + 6_250,
      span_hz: 500_000,
      sample_rate_hz: 500_000,
      expected_bandwidth_hz: [6_250, 12_500],
      modulation: ['NFM', 'FM'],
      temporal_pattern: 'bursty_voice',
      capture_duration_seconds: 20,
      recommended_gain_db: 25,
      training_note:
        'Legal licence-free PMR446 walkie-talkie profile for Spain and Europe. Good for short-range voice burst detection and controlled RF fingerprinting if the same channel, distance, gain and antenna orientation are kept stable.',
    },
  ];
}) as Array<[string, RFProfile]>;

const PMR446_ANALOG_PROFILES = Object.fromEntries(PMR446_ANALOG_CHANNELS) as Record<string, RFProfile>;

const PMR446_DIGITAL_6K25_CHANNELS = Array.from({ length: 32 }, (_, index) => {
  const channel = index + 1;
  const center_frequency_hz = 446_003_125 + index * 6_250;
  const key = `pmr446_digital_6k25_ch${channel}`;

  return [
    key,
    {
      key,
      label: `PMR446 Digital 6.25 kHz Channel ${channel}`,
      family: 'pmr446_walkie_talkie',
      signal_type: 'pmr446_digital_voice',
      center_frequency_hz,
      marker_left_hz: center_frequency_hz - 3_125,
      marker_right_hz: center_frequency_hz + 3_125,
      span_hz: 500_000,
      sample_rate_hz: 500_000,
      expected_bandwidth_hz: [6_250],
      modulation: ['4FSK', 'C4FM', 'Digital_Voice'],
      temporal_pattern: 'bursty_voice_frames',
      capture_duration_seconds: 20,
      recommended_gain_db: 25,
      training_note:
        'Digital PMR446 6.25 kHz profile. Use for digital walkie-talkie signal observation and fingerprinting only with controlled devices and stable SDR settings.',
    },
  ];
}) as Array<[string, RFProfile]>;

const PMR446_DIGITAL_6K25_PROFILES = Object.fromEntries(PMR446_DIGITAL_6K25_CHANNELS) as Record<string, RFProfile>;





export const RF_PROFILES: Record<string, RFProfile> = {
  fm_broadcast_europe: {
    key: 'fm_broadcast_europe',
    label: 'WFM Broadcast Europe',
    family: 'broadcast_fm',
    signal_type: 'wideband_fm_broadcast',
    center_frequency_hz: 98_500_000,
    marker_left_hz: 98_400_000,
    marker_right_hz: 98_600_000,
    span_hz: 1_000_000,
    sample_rate_hz: 1_000_000,
    expected_bandwidth_hz: [120_000, 200_000],
    modulation: ['WFM'],
    temporal_pattern: 'continuous',
    capture_duration_seconds: 5,
    recommended_gain_db: 20,
    training_note: 'Continuous broadcast signal. Useful for receiver validation, not ideal for transmitter fingerprinting unless the emitter is known and stable.',
  },
  airband_civil_vhf_25khz: {
    key: 'airband_civil_vhf_25khz',
    label: 'Civil Aviation VHF Voice',
    family: 'aviation_vhf',
    signal_type: 'narrowband_am_voice',
    center_frequency_hz: 125_000_000,
    marker_left_hz: 124_987_500,
    marker_right_hz: 125_012_500,
    span_hz: 500_000,
    sample_rate_hz: 500_000,
    expected_bandwidth_hz: [8_330, 25_000],
    modulation: ['AM'],
    temporal_pattern: 'bursty_voice',
    capture_duration_seconds: 20,
    recommended_gain_db: 25,
    training_note: 'Bursty AM voice channel. Use only for visual and modulation detection unless transmitter identity is controlled.',
  },
  noaa_apt_137_100: {
    key: 'noaa_apt_137_100',
    label: 'NOAA APT 137.100 MHz',
    family: 'satellite_leo',
    signal_type: 'weather_satellite_apt',
    center_frequency_hz: 137_100_000,
    marker_left_hz: 137_080_000,
    marker_right_hz: 137_120_000,
    span_hz: 250_000,
    sample_rate_hz: 250_000,
    expected_bandwidth_hz: [34_000, 40_000],
    modulation: ['WFM', 'AM_Subcarrier'],
    temporal_pattern: 'continuous_during_pass',
    capture_duration_seconds: 60,
    recommended_gain_db: 30,
    training_note: 'Useful for satellite pass decoding and visual spectrum validation. Not suitable for local IoT fingerprinting.',
  },

  dacia_remote_433_ook: {
  key: 'dacia_remote_433_ook',
  label: 'Dacia 433.92 MHz OOK Remote Key',
  family: 'automotive_remote',
  signal_type: 'vehicle_remote_key',

  center_frequency_hz: 433_965_776,

  // Real analysis/capture span: 0.7 MHz centered at 433.965776 MHz
  marker_left_hz: 433_615_809,
  marker_right_hz: 434_315_744,

  span_hz: 700_000,
  sample_rate_hz: 700_000,

  expected_bandwidth_hz: [10_000, 100_000],
  modulation: ['OOK', 'ASK'],
  temporal_pattern: 'short_bursts',

  capture_duration_seconds: 5,
  recommended_gain_db: 25,

  training_note: 'Profile for Dacia remote-key RF fingerprinting. Keep distance, gain, antenna orientation and capture duration stable across repeated captures.',
},



remote_433_ook: {
  key: 'remote_433_ook',
  label: '433.92 MHz OOK Remote',
  family: 'ism_remote',
  signal_type: 'short_range_remote_control',

  center_frequency_hz: 433_920_000,

  // Real analysis/capture span: 1.5 MHz centered at 433.92 MHz
  marker_left_hz: 433_170_000,
  marker_right_hz: 434_670_000,

  span_hz: 1_500_000,
  sample_rate_hz: 1_500_000,

  expected_bandwidth_hz: [10_000, 100_000],
  modulation: ['OOK', 'ASK'],
  temporal_pattern: 'short_bursts',

  capture_duration_seconds: 5,
  recommended_gain_db: 25,

  training_note: 'Good profile for transmitter fingerprinting. Keep distance, gain, antenna and capture duration stable across devices.',
},
  ism_868_lora_125khz: {
    key: 'ism_868_lora_125khz',
    label: '868 MHz LoRa 125 kHz',
    family: 'ism_iot_lora',
    signal_type: 'lora_css_packet',
    center_frequency_hz: 868_100_000,
    marker_left_hz: 868_037_500,
    marker_right_hz: 868_162_500,
    span_hz: 1_000_000,
    sample_rate_hz: 1_000_000,
    expected_bandwidth_hz: [125_000],
    modulation: ['LoRa_CSS'],
    temporal_pattern: 'packet_bursts',
    capture_duration_seconds: 10,
    recommended_gain_db: 25,
    training_note: 'Good IoT fingerprinting profile when devices transmit on a fixed LoRa channel. Keep spreading factor and bandwidth metadata if available.',
  },
  ism_868_fsk: {
    key: 'ism_868_fsk',
    label: '868 MHz FSK IoT',
    family: 'ism_iot_fsk',
    signal_type: 'narrowband_fsk_iot',
    center_frequency_hz: 868_300_000,
    marker_left_hz: 868_200_000,
    marker_right_hz: 868_400_000,
    span_hz: 1_000_000,
    sample_rate_hz: 1_000_000,
    expected_bandwidth_hz: [25_000, 50_000, 100_000],
    modulation: ['2-FSK', 'GFSK'],
    temporal_pattern: 'packet_bursts',
    capture_duration_seconds: 10,
    recommended_gain_db: 25,
    training_note: 'Good for IoT transmitter fingerprinting if the same protocol and channel are used across all devices.',
  },
  adsb_1090: {
    key: 'adsb_1090',
    label: 'ADS-B 1090 MHz',
    family: 'aviation_adsb',
    signal_type: 'adsb_mode_s_ppm',
    center_frequency_hz: 1_090_000_000,
    marker_left_hz: 1_089_000_000,
    marker_right_hz: 1_091_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [2_000_000],
    modulation: ['PPM'],
    temporal_pattern: 'short_pulse_bursts',
    capture_duration_seconds: 10,
    recommended_gain_db: 30,
    training_note: 'Useful for pulse detection and aircraft signal analysis. Not ideal for controlled lab fingerprinting unless transmitter source is known.',
  },
  ble_adv_37: {
    key: 'ble_adv_37',
    label: 'BLE Advertising Channel 37',
    family: 'bluetooth_low_energy',
    signal_type: 'ble_advertising_gfsk',
    center_frequency_hz: 2_402_000_000,
    marker_left_hz: 2_401_000_000,
    marker_right_hz: 2_403_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [1_000_000, 2_000_000],
    modulation: ['GFSK'],
    temporal_pattern: 'advertising_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Recommended BLE fingerprinting profile. Capture the same advertising channel for all devices and keep the same SDR settings.',
  },
  ble_adv_38: {
    key: 'ble_adv_38',
    label: 'BLE Advertising Channel 38',
    family: 'bluetooth_low_energy',
    signal_type: 'ble_advertising_gfsk',
    center_frequency_hz: 2_426_000_000,
    marker_left_hz: 2_425_000_000,
    marker_right_hz: 2_427_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [1_000_000, 2_000_000],
    modulation: ['GFSK'],
    temporal_pattern: 'advertising_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Recommended BLE fingerprinting profile. Use the same channel and same configuration across all devices.',
  },
  ble_adv_39: {
    key: 'ble_adv_39',
    label: 'BLE Advertising Channel 39',
    family: 'bluetooth_low_energy',
    signal_type: 'ble_advertising_gfsk',
    center_frequency_hz: 2_480_000_000,
    marker_left_hz: 2_479_000_000,
    marker_right_hz: 2_481_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [1_000_000, 2_000_000],
    modulation: ['GFSK'],
    temporal_pattern: 'advertising_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Recommended BLE fingerprinting profile. Channel 39 is useful but may be more affected by Wi-Fi depending on the environment.',
  },
  cc2540_ble_adv_37: {
    key: 'cc2540_ble_adv_37',
    label: 'TI CC2540 BLE Advertising CH37',
    family: 'bluetooth_low_energy',
    signal_type: 'cc2540_ble_advertising',
    center_frequency_hz: 2_402_000_000,
    marker_left_hz: 2_401_000_000,
    marker_right_hz: 2_403_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [1_000_000],
    modulation: ['GFSK'],
    temporal_pattern: 'advertising_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Specific BLE profile for TI CC2540-like emitters. Use this when building a controlled dataset from CC2540 devices.',
  },

  pmr446_band_monitor_spain: {
    key: 'pmr446_band_monitor_spain',
    label: 'PMR446 Spain / Europe Band Monitor',
    family: 'pmr446_walkie_talkie',
    signal_type: 'pmr446_band_activity',
    center_frequency_hz: 446_100_000,
    marker_left_hz: 446_000_000,
    marker_right_hz: 446_200_000,
    span_hz: 500_000,
    sample_rate_hz: 500_000,
    expected_bandwidth_hz: [6_250, 12_500],
    modulation: ['NFM', 'FM', '4FSK', 'C4FM', 'Digital_Voice'],
    temporal_pattern: 'bursty_voice_or_digital_frames',
    capture_duration_seconds: 30,
    recommended_gain_db: 25,
    training_note:
      'Wide PMR446 monitoring profile for Spain and Europe. Use this first to detect active walkie-talkie channels across 446.0-446.2 MHz, then switch to the exact analog or digital channel profile for dataset capture.',
  },

  ...PMR446_ANALOG_PROFILES,
  ...PMR446_DIGITAL_6K25_PROFILES,

    cc2650stk_ble_adv_37: {
    key: 'cc2650stk_ble_adv_37',
    label: 'TI SensorTag CC2650STK BLE Advertising CH37',
    family: 'bluetooth_low_energy',
    signal_type: 'cc2650stk_ble_advertising',
    center_frequency_hz: 2_402_000_000,
    marker_left_hz: 2_401_000_000,
    marker_right_hz: 2_403_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [1_000_000],
    modulation: ['GFSK'],
    temporal_pattern: 'advertising_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Specific BLE advertising profile for TI SimpleLink SensorTag CC2650STK emitters. Use this when building a controlled RF fingerprinting dataset from CC2650STK devices on BLE advertising channel 37.',
  },

  cc2650stk_ble_adv_38: {
    key: 'cc2650stk_ble_adv_38',
    label: 'TI SensorTag CC2650STK BLE Advertising CH38',
    family: 'bluetooth_low_energy',
    signal_type: 'cc2650stk_ble_advertising',
    center_frequency_hz: 2_426_000_000,
    marker_left_hz: 2_425_000_000,
    marker_right_hz: 2_427_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [1_000_000],
    modulation: ['GFSK'],
    temporal_pattern: 'advertising_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Specific BLE advertising profile for TI SimpleLink SensorTag CC2650STK emitters. Use this when building a controlled RF fingerprinting dataset from CC2650STK devices on BLE advertising channel 38.',
  },

  cc2650stk_ble_adv_39: {
    key: 'cc2650stk_ble_adv_39',
    label: 'TI SensorTag CC2650STK BLE Advertising CH39',
    family: 'bluetooth_low_energy',
    signal_type: 'cc2650stk_ble_advertising',
    center_frequency_hz: 2_480_000_000,
    marker_left_hz: 2_479_000_000,
    marker_right_hz: 2_481_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [1_000_000],
    modulation: ['GFSK'],
    temporal_pattern: 'advertising_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Specific BLE advertising profile for TI SimpleLink SensorTag CC2650STK emitters. Use this when building a controlled RF fingerprinting dataset from CC2650STK devices on BLE advertising channel 39.',
  },


  zigbee_24g_ch11: {
    key: 'zigbee_24g_ch11',
    label: 'ZigBee 2.4 GHz Channel 11',
    family: 'zigbee_802154',
    signal_type: 'ieee_802154_oqpsk',
    center_frequency_hz: 2_405_000_000,
    marker_left_hz: 2_404_000_000,
    marker_right_hz: 2_406_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [2_000_000],
    modulation: ['O-QPSK'],
    temporal_pattern: 'short_packet_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Good profile for 802.15.4 fingerprinting if devices are forced to the same ZigBee channel.',
  },
  zigbee_24g_ch15: {
    key: 'zigbee_24g_ch15',
    label: 'ZigBee 2.4 GHz Channel 15',
    family: 'zigbee_802154',
    signal_type: 'ieee_802154_oqpsk',
    center_frequency_hz: 2_425_000_000,
    marker_left_hz: 2_424_000_000,
    marker_right_hz: 2_426_000_000,
    span_hz: 4_000_000,
    sample_rate_hz: 4_000_000,
    expected_bandwidth_hz: [2_000_000],
    modulation: ['O-QPSK'],
    temporal_pattern: 'short_packet_bursts',
    capture_duration_seconds: 20,
    recommended_gain_db: 30,
    training_note: 'Use this profile when the ZigBee network is configured on channel 15.',
  },
  wifi_24g_ch1: {
    key: 'wifi_24g_ch1',
    label: 'Wi-Fi 2.4 GHz Channel 1',
    family: 'wifi_80211',
    signal_type: 'wifi_ofdm_dsss',
    center_frequency_hz: 2_412_000_000,
    marker_left_hz: 2_402_000_000,
    marker_right_hz: 2_422_000_000,
    span_hz: 30_000_000,
    sample_rate_hz: 30_000_000,
    expected_bandwidth_hz: [20_000_000],
    modulation: ['DSSS', 'OFDM'],
    temporal_pattern: 'bursty_frames',
    capture_duration_seconds: 10,
    recommended_gain_db: 20,
    training_note: 'Use for Wi-Fi fingerprinting only if devices transmit on the same channel. Avoid mixing channels during training.',
  },
  wifi_24g_ch6: {
    key: 'wifi_24g_ch6',
    label: 'Wi-Fi 2.4 GHz Channel 6',
    family: 'wifi_80211',
    signal_type: 'wifi_ofdm_dsss',
    center_frequency_hz: 2_437_000_000,
    marker_left_hz: 2_427_000_000,
    marker_right_hz: 2_447_000_000,
    span_hz: 30_000_000,
    sample_rate_hz: 30_000_000,
    expected_bandwidth_hz: [20_000_000],
    modulation: ['DSSS', 'OFDM'],
    temporal_pattern: 'bursty_frames',
    capture_duration_seconds: 10,
    recommended_gain_db: 20,
    training_note: 'Use for Wi-Fi fingerprinting on channel 6. Keep router, channel width, distance and traffic generation stable.',
  },
  wifi_24g_ch11: {
    key: 'wifi_24g_ch11',
    label: 'Wi-Fi 2.4 GHz Channel 11',
    family: 'wifi_80211',
    signal_type: 'wifi_ofdm_dsss',
    center_frequency_hz: 2_462_000_000,
    marker_left_hz: 2_452_000_000,
    marker_right_hz: 2_472_000_000,
    span_hz: 30_000_000,
    sample_rate_hz: 30_000_000,
    expected_bandwidth_hz: [20_000_000],
    modulation: ['DSSS', 'OFDM'],
    temporal_pattern: 'bursty_frames',
    capture_duration_seconds: 10,
    recommended_gain_db: 20,
    training_note: 'Use for Wi-Fi fingerprinting on channel 11. Do not mix captures from other Wi-Fi channels in the same training class.',
  },
  ...WIFI_5GHZ_PROFILES,
  gps_l1: {
    key: 'gps_l1',
    label: 'GPS L1 / Galileo E1',
    family: 'gnss',
    signal_type: 'gnss_spread_spectrum',
    center_frequency_hz: 1_575_420_000,
    marker_left_hz: 1_573_374_000,
    marker_right_hz: 1_577_466_000,
    span_hz: 6_000_000,
    sample_rate_hz: 6_000_000,
    expected_bandwidth_hz: [2_046_000, 4_092_000],
    modulation: ['BPSK', 'BOC'],
    temporal_pattern: 'continuous_spread_spectrum',
    capture_duration_seconds: 30,
    recommended_gain_db: 35,
    training_note: 'Useful for GNSS signal observation. Not recommended for local transmitter fingerprinting.',
  },
  lte_b7_downlink_2655: {
    key: 'lte_b7_downlink_2655',
    label: 'LTE Band 7 Downlink 2655 MHz',
    family: 'cellular_lte',
    signal_type: 'lte_downlink_ofdm',
    center_frequency_hz: 2_655_000_000,
    marker_left_hz: 2_645_000_000,
    marker_right_hz: 2_665_000_000,
    span_hz: 30_000_000,
    sample_rate_hz: 30_000_000,
    expected_bandwidth_hz: [5_000_000, 10_000_000, 20_000_000],
    modulation: ['OFDM', 'QAM'],
    temporal_pattern: 'continuous_downlink',
    capture_duration_seconds: 10,
    recommended_gain_db: 20,
    training_note: 'Useful for OFDM profile detection. Not suitable for fingerprinting individual user devices from downlink.',
  },
  nr_n78_3500: {
    key: 'nr_n78_3500',
    label: '5G NR n78 3500 MHz',
    family: 'cellular_5g',
    signal_type: 'nr_tdd_ofdm',
    center_frequency_hz: 3_500_000_000,
    marker_left_hz: 3_485_000_000,
    marker_right_hz: 3_515_000_000,
    span_hz: 30_000_000,
    sample_rate_hz: 30_000_000,
    expected_bandwidth_hz: [20_000_000, 40_000_000, 100_000_000],
    modulation: ['OFDM', 'QAM'],
    temporal_pattern: 'tdd_ofdm_frames',
    capture_duration_seconds: 10,
    recommended_gain_db: 20,
    training_note: 'Use only as a visual and signal-type profile unless the transmitter and channel are controlled.',
  },
};

export const RF_PROFILE_LIST = Object.values(RF_PROFILES);

export function applyRFProfile(profile: RFProfile): AppliedRFProfile {
  const start_frequency_hz = profile.center_frequency_hz - profile.span_hz / 2;
  const stop_frequency_hz = profile.center_frequency_hz + profile.span_hz / 2;
  return {
    selected_profile_key: profile.key,
    center_frequency_hz: profile.center_frequency_hz,
    start_frequency_hz,
    stop_frequency_hz,
    span_hz: profile.span_hz,
    sample_rate_hz: profile.sample_rate_hz,
    marker_left_hz: profile.marker_left_hz,
    marker_right_hz: profile.marker_right_hz,
    markers: [
      {
        id: `${profile.key}_left`,
        label: `${profile.label} left`,
        frequency_hz: profile.marker_left_hz,
        type: 'profile_left_marker',
      },
      {
        id: `${profile.key}_right`,
        label: `${profile.label} right`,
        frequency_hz: profile.marker_right_hz,
        type: 'profile_right_marker',
      },
      {
        id: `${profile.key}_center`,
        label: `${profile.label} center`,
        frequency_hz: profile.center_frequency_hz,
        type: 'profile_center_marker',
      },
    ],
    signal_type: profile.signal_type,
    family: profile.family,
    modulation: profile.modulation,
    temporal_pattern: profile.temporal_pattern,
    expected_bandwidth_hz: profile.expected_bandwidth_hz,
    capture_duration_seconds: profile.capture_duration_seconds,
    recommended_gain_db: profile.recommended_gain_db,
    training_note: profile.training_note,
  };
}
