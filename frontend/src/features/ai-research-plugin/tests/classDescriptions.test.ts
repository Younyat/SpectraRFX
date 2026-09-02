import { describe, expect, it } from 'vitest';
import { formatClassDescriptions, parseClassDescriptions } from '../ui/AiResearchPluginView';

describe('parseClassDescriptions', () => {
  it('parses one "NAME: description" per line', () => {
    expect(parseClassDescriptions('BPSK: Binary Phase Shift Keying\nQPSK: Quadrature Phase Shift Keying')).toEqual({
      BPSK: 'Binary Phase Shift Keying',
      QPSK: 'Quadrature Phase Shift Keying',
    });
  });

  it('handles a description that itself contains a colon', () => {
    expect(parseClassDescriptions('BPSK: 1 bit/symbol: simplest PSK variant')).toEqual({
      BPSK: '1 bit/symbol: simplest PSK variant',
    });
  });

  it('skips blank lines and lines without a colon rather than throwing', () => {
    expect(parseClassDescriptions('BPSK: real one\n\nnot a valid line\nQPSK: another real one')).toEqual({
      BPSK: 'real one',
      QPSK: 'another real one',
    });
  });

  it('skips a line with an empty name or empty description', () => {
    expect(parseClassDescriptions(': no name\nBPSK: \nQPSK: real')).toEqual({ QPSK: 'real' });
  });

  it('returns an empty object for empty input', () => {
    expect(parseClassDescriptions('')).toEqual({});
  });
});

describe('formatClassDescriptions', () => {
  it('round-trips through parseClassDescriptions', () => {
    const original = { BPSK: 'Binary Phase Shift Keying', QPSK: 'Quadrature Phase Shift Keying' };
    expect(parseClassDescriptions(formatClassDescriptions(original))).toEqual(original);
  });

  it('returns an empty string for null/undefined', () => {
    expect(formatClassDescriptions(null)).toBe('');
    expect(formatClassDescriptions(undefined)).toBe('');
  });
});
