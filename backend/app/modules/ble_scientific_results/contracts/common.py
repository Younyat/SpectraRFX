"""Re-exports BLE-RFFI Studio's own immutable-contract machinery instead of
duplicating it. `AnalysisContract` and every other contract in this package
needs exactly the same guarantee ExampleRecord/DatasetManifest already rely
on -- frozen pydantic models, canonical-JSON content hashing -- so this
package imports it directly rather than re-deriving it.
"""
from __future__ import annotations

from app.modules.ble_rffi_studio.contracts import StudioContract, identity_hash

__all__ = ["StudioContract", "identity_hash"]
