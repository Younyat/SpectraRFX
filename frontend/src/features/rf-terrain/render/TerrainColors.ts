export type TerrainColormap = 'turbo' | 'viridis' | 'grayscale';

// Polynomial approximation of Google's Turbo colormap (public domain,
// Anton Mikhailov 2019). Cheap enough to call per-vertex on the CPU for a
// 512x240 mesh without a lookup texture.
const turbo = (t: number): [number, number, number] => {
  const x = Math.min(1, Math.max(0, t));
  const r = 34.61 + x * (1172.33 + x * (-10793.56 + x * (33300.12 + x * (-38394.49 + x * 14825.05))));
  const g = 23.31 + x * (557.33 + x * (1225.33 + x * (-3574.96 + x * (1073.77 + x * 707.56))));
  const b = 27.2 + x * (3211.1 + x * (-15327.97 + x * (27814.0 + x * (-22569.18 + x * 6838.66))));
  return [
    Math.max(0, Math.min(255, r)) / 255,
    Math.max(0, Math.min(255, g)) / 255,
    Math.max(0, Math.min(255, b)) / 255,
  ];
};

const viridisStops: Array<[number, number, number]> = [
  [0.267, 0.005, 0.329], [0.283, 0.141, 0.458], [0.254, 0.265, 0.530],
  [0.207, 0.372, 0.553], [0.164, 0.471, 0.558], [0.128, 0.567, 0.551],
  [0.135, 0.659, 0.518], [0.267, 0.749, 0.441], [0.478, 0.821, 0.318],
  [0.741, 0.873, 0.150], [0.993, 0.906, 0.144],
];

const viridis = (t: number): [number, number, number] => {
  const x = Math.min(1, Math.max(0, t)) * (viridisStops.length - 1);
  const i = Math.floor(x);
  const frac = x - i;
  const a = viridisStops[i];
  const b = viridisStops[Math.min(i + 1, viridisStops.length - 1)];
  return [a[0] + (b[0] - a[0]) * frac, a[1] + (b[1] - a[1]) * frac, a[2] + (b[2] - a[2]) * frac];
};

const grayscale = (t: number): [number, number, number] => {
  const v = Math.min(1, Math.max(0, t));
  return [v, v, v];
};

export const colormapFor = (name: TerrainColormap) => {
  switch (name) {
    case 'viridis':
      return viridis;
    case 'grayscale':
      return grayscale;
    case 'turbo':
    default:
      return turbo;
  }
};
