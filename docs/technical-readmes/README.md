# Technical READMEs — per-technology audit trail

This directory is the single place where the *technical how* of getting each
wireless technology working in this platform is recorded: what was
implemented, what mathematical/DSP techniques were used, what the exact call
chain is end to end, what bugs were found and fixed along the way, and how to
reproduce and verify the result. It exists so that a programmer with **no
prior context** on a given technology can read one document and rebuild or
extend the capability without having to reconstruct the history from git log
or from a chat transcript.

## Convention

```
docs/technical-readmes/
  README.md              <- this index
  <technology>/
    README.md             <- the full technical writeup for that technology
```

One subdirectory per technology (`wifi_80211/`, `ble/`, ...). Each
subdirectory's `README.md` must stand alone: architecture, exact files touched,
signal-processing/math implemented, known bugs and fixes, step-by-step
reproduction instructions, verification steps, and known open limitations.
When a technology's implementation changes meaningfully, update its README in
the same change — this is documentation-as-audit-trail, not a one-time diary
entry.

Module-local rule: when a concrete code module is modified in a way that
changes behavior, gates, evidence handling, acquisition policy, model policy,
or scientific interpretation, that module must also contain or update a local
technical `README.md`. The local README records the programmer-facing details:
technical change, scientific reason, affected gate/status, verification
artifacts, and remaining claim boundaries. The technology README remains the
high-level map; the module README is the maintenance memory next to the code.

## Index

| Technology | Status | Document |
|---|---|---|
| IEEE 802.11 (Wi-Fi) | Partial recovery, real over-the-air frames confirmed (not all frames recovered) | [wifi_80211/README.md](wifi_80211/README.md) |
| Bluetooth Low Energy (BLE) | Two efforts: a frozen Gate 1B bitstream-replay pipeline is integrated (no RF/IQ); a separate, active Gate 2A.2 DSP/IQ-recovery receiver (not frozen) now has an experimental, off-by-default *offline IQ file analysis* bridge integrated — SDR capture and combined capture+decode stay disabled until a candidate is frozen and passes an independent holdout | [ble/README.md](ble/README.md) |
