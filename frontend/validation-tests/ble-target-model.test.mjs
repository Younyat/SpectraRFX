import test from 'node:test';import assert from 'node:assert/strict';
import {orderTargetDevices,preserveSelectedTarget,freezeTarget} from '../.ble-validation/bleTargetModel.js';
const old={device_id:'legacy',address:'BC:6A:29:AB:DE:13',last_seen_utc:'2026-07-16T00:00:00Z',scan_session_id:'old',profile_label:'CC2541'};
const current={device_id:'other',address:'11:22:33:44:55:66',last_seen_utc:'2026-07-17T00:00:00Z',scan_session_id:'scan-2'};
test('scan refresh prioritizes SensorTag and preserves selection',()=>{const ordered=orderTargetDevices([current,old],'scan-2');assert.equal(ordered[0].device_id,'legacy');assert.equal(preserveSelectedTarget('legacy',[current,old]),'legacy')});
test('campaign freezes historical target identity',()=>{assert.deepEqual(freezeTarget(old,'scan-2'),{kind:'device',device_id:'legacy',address:'BC:6A:29:AB:DE:13',label:'CC2541',selection_source:'native_registry_history'})});
