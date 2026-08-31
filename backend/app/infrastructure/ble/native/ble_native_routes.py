from __future__ import annotations

from fastapi import APIRouter, HTTPException


def build_ble_native_router(manager):
    router = APIRouter(prefix="/ble/native", tags=["ble-native-adapter"])
    def call(fn):
        try: return fn()
        except KeyError as error: raise HTTPException(404, "BLE_DEVICE_OR_CHARACTERISTIC_NOT_FOUND") from error
        except PermissionError as error: raise HTTPException(409, str(error)) from error
        except RuntimeError as error: raise HTTPException(503, str(error)) from error
        except Exception as error: raise HTTPException(500, f"NATIVE_BLE_ERROR:{type(error).__name__}:{error}") from error

    @router.get("/status")
    def status(): return call(manager.status)
    @router.post("/scan/start")
    def start_scan(body: dict | None = None): return call(lambda: manager.start_scan((body or {}).get("session_id")))
    @router.post("/scan/stop")
    def stop_scan(): return call(manager.stop_scan)
    @router.get("/devices")
    def devices(): return {"devices": call(manager.devices)}
    @router.get("/devices/{device_id}")
    def device(device_id: str): return call(lambda: manager.device(device_id))
    @router.post("/devices/{device_id}/connect", status_code=202)
    def connect(device_id: str): return call(lambda: manager.start_connection(device_id))
    @router.get("/connection-jobs/{job_id}")
    def connection_job(job_id: str): return call(lambda: manager.connection_job(job_id))
    @router.post("/connection-jobs/{job_id}/cancel")
    def cancel_connection(job_id: str): return call(lambda: manager.cancel_connection(job_id))
    @router.post("/devices/{device_id}/disconnect")
    def disconnect(device_id: str): return call(lambda: manager.disconnect(device_id))
    @router.get("/devices/{device_id}/services")
    def services(device_id: str): return {"services": call(lambda: manager.services(device_id))}
    @router.get("/devices/{device_id}/gatt-diagnostics")
    def diagnostics(device_id: str): return call(lambda: manager.diagnostic_report(device_id))
    @router.post("/devices/{device_id}/characteristics/{characteristic_uuid}/read")
    def read(device_id: str, characteristic_uuid: str): return call(lambda: manager.read(device_id, characteristic_uuid))
    @router.post("/devices/{device_id}/characteristics/{characteristic_uuid}/subscribe")
    def subscribe(device_id: str, characteristic_uuid: str): return call(lambda: manager.subscribe(device_id, characteristic_uuid))
    @router.post("/devices/{device_id}/characteristics/{characteristic_uuid}/unsubscribe")
    def unsubscribe(device_id: str, characteristic_uuid: str): return call(lambda: manager.unsubscribe(device_id, characteristic_uuid))
    @router.post("/devices/{device_id}/environmental/start")
    def start_environmental(device_id: str): return call(lambda: manager.start_environmental_measurements(device_id))
    @router.post("/devices/{device_id}/environmental/stop")
    def stop_environmental(device_id: str): return call(lambda: manager.stop_environmental_measurements(device_id))
    @router.post("/devices/{device_id}/ir-temperature/start")
    def start_ir_temperature(device_id: str): return call(lambda: manager.start_ir_temperature_measurements(device_id))
    @router.post("/devices/{device_id}/ir-temperature/stop")
    def stop_ir_temperature(device_id: str): return call(lambda: manager.stop_ir_temperature_measurements(device_id))
    @router.post("/devices/{device_id}/sensors/{sensor_name}/start")
    def start_sensor(device_id:str,sensor_name:str):return call(lambda:manager.start_legacy_sensor(device_id,sensor_name))
    @router.post("/devices/{device_id}/sensors/{sensor_name}/stop")
    def stop_sensor(device_id:str,sensor_name:str):return call(lambda:manager.stop_legacy_sensor(device_id,sensor_name))
    @router.post("/devices/{device_id}/sensors/start-supported")
    def start_supported(device_id:str):return call(lambda:manager.start_supported_sensors(device_id))
    @router.get("/inventory")
    def inventory(): return call(manager.inventory)
    return router
