export const RF_TERRAIN_MODULE_ID = 'rf-terrain';
export const RF_TERRAIN_PATH = '/rf-terrain';
export const RF_TERRAIN_LEGACY_WATERFALL_PATH = '/waterfall';

// Default history depth (spec §44/§97): 240 rows -- a non-universal starting
// point the spec itself flags for later experimental tuning, not a fixed law.
export const RF_TERRAIN_DEFAULT_HISTORY_ROWS = 240;

// Rewind window (bounded on purpose -- "not too old, so it doesn't load the
// system much"): keeps 3x the live render depth in the main-thread history
// cache (~72s at the default 100ms poll interval), never unbounded. This is
// a small, capped lookback inside the existing ring buffer depth, not the
// full multiresolution "Spectral Geology" long-history feature (out of
// scope for this pass).
export const RF_TERRAIN_EXTENDED_HISTORY_ROWS = RF_TERRAIN_DEFAULT_HISTORY_ROWS * 3;
export const RF_TERRAIN_REWIND_MAX_OFFSET_ROWS = RF_TERRAIN_EXTENDED_HISTORY_ROWS - RF_TERRAIN_DEFAULT_HISTORY_ROWS;

// Single frame producer poll cadence (spec §9). Kept independent from
// RUNTIME_CONFIG.spectrumPollIntervalMs so RF Terrain's own poller can be
// tuned without changing Live Monitor's.
export const RF_TERRAIN_POLL_INTERVAL_MS = 100;

// Rendered/analysis frequency resolution (spec §44/§97) -- a documented
// starting point, not a universal law. The native FFT (e.g. 4096 bins) is
// resampled down to this before both rendering AND the ARST engines below;
// the spec's ideal of full-precision analysis alongside a coarser render
// mesh is not implemented in this pass (documented simplification).
export const RF_TERRAIN_DEFAULT_FREQUENCY_BINS = 512;

// Adaptive noise floor (spec §18): initial quantile/window, both flagged by
// the spec itself as needing experimental validation, not fixed constants.
export const RF_TERRAIN_NOISE_QUANTILE = 0.2;
export const RF_TERRAIN_NOISE_WINDOW_SECONDS = 3;
export const RF_TERRAIN_NOISE_SMOOTHING_BETA = 0.7;

// Persistence (spec §19/§97).
export const RF_TERRAIN_PERSISTENCE_THRESHOLD_DB = 6;
export const RF_TERRAIN_PERSISTENCE_TAU_SECONDS = 2;

// Occupancy time constant -- an exponential approximation of the spec's
// real-Δt-weighted windowed ratio (§20), documented in occupancyEngine.ts.
export const RF_TERRAIN_OCCUPANCY_TAU_SECONDS = 20;

// Max terrain excess / height clip (spec §17/§97).
export const RF_TERRAIN_MAX_EXCESS_DB = 40;

// Terrain object segmentation hysteresis (dual threshold, documented
// starting points -- not a calibrated model). A component must contain at
// least one cell above the SEED threshold to be created; once seeded, it
// grows through neighbors above the lower GROW threshold. This absorbs a
// single real emission's own small dips instead of fracturing it into many
// slivers at the exact 6dB single-threshold boundary used by persistence/
// occupancy above.
export const RF_TERRAIN_SEGMENTATION_SEED_THRESHOLD_DB = 8;
export const RF_TERRAIN_SEGMENTATION_GROW_THRESHOLD_DB = 6;
export const RF_TERRAIN_SEGMENTATION_MIN_CELL_COUNT = 2;

// DENSITY mode's frequency-axis smoothing radius (documented starting
// point): a triangular kernel spanning `2*radius+1` bins, e.g. radius=2
// -> 5 bins wide. Purely a rendering/readability parameter -- it never
// changes any value the Inspector, holds, or terrain-object engines see.
export const RF_TERRAIN_DENSITY_SMOOTHING_RADIUS = 2;

// RAW mode display range (spec §16) -- purely a visual normalization for
// height/color in the reference mode, distinct from any scientific value.
export const RF_TERRAIN_RAW_DISPLAY_MIN_DB = -100;
export const RF_TERRAIN_RAW_DISPLAY_MAX_DB = -20;

// Purely visual height exaggeration (never applied to the real dB values
// stored for the inspector/raycaster, spec §67/§96): the mesh is ~cols
// wide but the raw 0-40dB excess range is small by comparison, so without
// exaggeration every emission reads as a faint ripple across a flat plain
// instead of an actual mountain.
export const RF_TERRAIN_HEIGHT_VISUAL_SCALE = 4;

