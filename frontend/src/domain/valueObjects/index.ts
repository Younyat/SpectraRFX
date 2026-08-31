import { parseFrequency, clamp } from '../../shared/utils';

export class Frequency {
  private readonly hertz: number;

  constructor(value: number, unit: 'Hz' | 'kHz' | 'MHz' | 'GHz' = 'Hz') {
    this.hertz = parseFrequency(value, unit);
    this.validate();
  }

  static fromHertz(hertz: number): Frequency {
    const freq = new Frequency(0);
    (freq as any).hertz = hertz;
    freq.validate();
    return freq;
  }

  get hertzValue(): number {
    return this.hertz;
  }

  get mhzValue(): number {
    return this.hertz / 1000000;
  }

  toString(): string {
    if (this.hertz >= 1000000000) {
      return `${(this.hertz / 1000000000).toFixed(2)} GHz`;
    } else if (this.hertz >= 1000000) {
      return `${(this.hertz / 1000000).toFixed(2)} MHz`;
    } else if (this.hertz >= 1000) {
      return `${(this.hertz / 1000).toFixed(2)} kHz`;
    } else {
      return `${this.hertz} Hz`;
    }
  }

  private validate() {
    if (this.hertz < 0) {
      throw new Error('Frequency cannot be negative');
    }
    if (this.hertz > 10000000000) { // 10 GHz max
      throw new Error('Frequency cannot exceed 10 GHz');
    }
  }
}

export class Gain {
  private readonly db: number;

  constructor(db: number) {
    this.db = clamp(db, -50, 50); // Typical SDR gain range
  }

  get dbValue(): number {
    return this.db;
  }

  toString(): string {
    return `${this.db >= 0 ? '+' : ''}${this.db.toFixed(1)} dB`;
  }
}

export class PowerLevel {
  private readonly dbm: number;

  constructor(dbm: number) {
    this.dbm = dbm;
  }

  get dbmValue(): number {
    return this.dbm;
  }

  get mwValue(): number {
    return Math.pow(10, this.dbm / 10);
  }

  toString(): string {
    return `${this.dbm >= 0 ? '+' : ''}${this.dbm.toFixed(1)} dBm`;
  }
}

export class Span {
  private readonly hertz: number;

  constructor(hertz: number) {
    this.hertz = Math.max(hertz, 1); // Minimum 1 Hz span
  }

  get hertzValue(): number {
    return this.hertz;
  }

  get khzValue(): number {
    return this.hertz / 1000;
  }

  get mhzValue(): number {
    return this.hertz / 1000000;
  }

  toString(): string {
    if (this.hertz >= 1000000) {
      return `${(this.hertz / 1000000).toFixed(2)} MHz`;
    } else if (this.hertz >= 1000) {
      return `${(this.hertz / 1000).toFixed(2)} kHz`;
    } else {
      return `${this.hertz} Hz`;
    }
  }
}

export class ResolutionBandwidth {
  private readonly hertz: number;

  constructor(hertz: number) {
    this.hertz = Math.max(hertz, 1); // Minimum 1 Hz RBW
  }

  get hertzValue(): number {
    return this.hertz;
  }

  toString(): string {
    if (this.hertz >= 1000) {
      return `${(this.hertz / 1000).toFixed(1)} kHz`;
    } else {
      return `${this.hertz} Hz`;
    }
  }
}

export class SampleRate {
  private readonly samplesPerSecond: number;

  constructor(samplesPerSecond: number) {
    this.samplesPerSecond = Math.max(samplesPerSecond, 1000); // Minimum 1 kHz
  }

  get samplesPerSecondValue(): number {
    return this.samplesPerSecond;
  }

  get mhzValue(): number {
    return this.samplesPerSecond / 1000000;
  }

  toString(): string {
    if (this.samplesPerSecond >= 1000000) {
      return `${(this.samplesPerSecond / 1000000).toFixed(1)} MS/s`;
    } else if (this.samplesPerSecond >= 1000) {
      return `${(this.samplesPerSecond / 1000).toFixed(1)} kS/s`;
    } else {
      return `${this.samplesPerSecond} S/s`;
    }
  }
}
