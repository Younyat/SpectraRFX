// A small, static reference dictionary of well-established modulation/
// technology abbreviations -- real, standard engineering terminology
// (not model-specific, not fabricated, not derived from any single
// model). Used ONLY as a FALLBACK display when a model's own operator-
// set `class_descriptions` has no entry for a predicted class name --
// never merged into or presented as if it were the model's own metadata.
// This is the one piece of "automation" that is honestly possible for
// arbitrary future imported models: if a model's class names happen to
// use standard terminology, this fills in without the operator typing
// anything; anything non-standard still needs a real, operator-typed
// description (there is no way to derive semantic meaning for an
// arbitrary class label from an ONNX file itself).
export const KNOWN_RF_TERMS: Record<string, string> = {
  // Digital phase/amplitude modulations
  BPSK: 'Binary Phase Shift Keying -- 2 phase states, 1 bit/symbol.',
  QPSK: 'Quadrature Phase Shift Keying -- 4 phase states, 2 bits/symbol.',
  '8PSK': '8-ary Phase Shift Keying -- 8 phase states, 3 bits/symbol.',
  OQPSK: 'Offset QPSK -- QPSK with staggered I/Q transitions, reduces envelope variation.',
  '16QAM': '16-ary Quadrature Amplitude Modulation -- 16 amplitude/phase states, 4 bits/symbol.',
  '32QAM': '32-ary Quadrature Amplitude Modulation -- 32 amplitude/phase states, 5 bits/symbol.',
  '64QAM': '64-ary Quadrature Amplitude Modulation -- 64 amplitude/phase states, 6 bits/symbol.',
  '128QAM': '128-ary Quadrature Amplitude Modulation -- 128 amplitude/phase states, 7 bits/symbol.',
  '256QAM': '256-ary Quadrature Amplitude Modulation -- 256 amplitude/phase states, 8 bits/symbol.',
  GMSK: 'Gaussian Minimum Shift Keying -- constant-envelope FSK with a Gaussian pre-filter (used by GSM, classic Bluetooth).',
  GFSK: 'Gaussian Frequency Shift Keying -- constant-envelope FSK with a Gaussian pre-filter (used by Bluetooth LE, many sub-GHz radios).',
  FSK: 'Frequency Shift Keying -- data encoded as discrete frequency shifts.',
  MSK: 'Minimum Shift Keying -- continuous-phase FSK with the minimum frequency separation for orthogonality.',
  PAM4: '4-level Pulse Amplitude Modulation -- 4 amplitude levels, 2 bits/symbol.',
  // Analog modulations
  'AM-DSB-SC': 'Amplitude Modulation, Double-Sideband Suppressed-Carrier.',
  'AM-SSB-SC': 'Amplitude Modulation, Single-Sideband Suppressed-Carrier.',
  'AM-SSB-WC': 'Amplitude Modulation, Single-Sideband With-Carrier.',
  'AM-DSB-WC': 'Amplitude Modulation, Double-Sideband With-Carrier (conventional broadcast AM).',
  WBFM: 'Wideband Frequency Modulation (e.g. FM broadcast radio).',
  NBFM: 'Narrowband Frequency Modulation (e.g. land-mobile/PMR voice radio).',
  CW: 'Continuous Wave -- an unmodulated or on/off keyed carrier (e.g. Morse code).',
  SSB: 'Single-Sideband modulation.',
  // Wireless technologies / standards
  'WI-FI': 'IEEE 802.11 wireless local area networking.',
  WIFI: 'IEEE 802.11 wireless local area networking.',
  '802.11': 'IEEE 802.11 wireless local area networking.',
  BLUETOOTH: 'Bluetooth Classic -- short-range 2.4 GHz wireless (GFSK/DPSK-based).',
  BLE: 'Bluetooth Low Energy -- low-power short-range 2.4 GHz wireless (GFSK-based).',
  ZIGBEE: 'IEEE 802.15.4-based low-power mesh networking (2.4 GHz or sub-GHz, O-QPSK typical).',
  LTE: '3GPP Long Term Evolution -- 4G cellular standard (OFDMA downlink).',
  '5G': '3GPP 5G New Radio cellular standard.',
  'NR': '3GPP New Radio -- the 5G radio access technology.',
  GSM: '2G cellular standard (GMSK-based).',
  DVB: 'Digital Video Broadcasting terrestrial/satellite/cable standard family.',
};

// Case/formatting-tolerant lookup -- model class names vary in casing and
// punctuation (e.g. "bpsk", "BPSK", "8-PSK") more than this small
// dictionary's canonical keys do.
export function lookupKnownRfTerm(className: string): string | null {
  const normalized = className.trim().toUpperCase().replace(/[\s_-]+/g, '');
  for (const [key, description] of Object.entries(KNOWN_RF_TERMS)) {
    if (key.replace(/[\s_-]+/g, '') === normalized) return description;
  }
  return null;
}
