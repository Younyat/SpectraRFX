from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse

def build_ble_dataset_router(manager):
    router=APIRouter(prefix="/ble/dataset-studio",tags=["ble-dataset-studio"])
    def call(fn):
        try:return fn()
        except FileNotFoundError as e:raise HTTPException(404,"DATASET_NOT_FOUND") from e
        except ValueError as e:raise HTTPException(400,str(e)) from e
        except RuntimeError as e:raise HTTPException(409,str(e)) from e
    @router.get("/definitions")
    def definitions():return manager.definitions()
    @router.get("/datasets")
    def datasets():return {"datasets":call(manager.list)}
    @router.post("/datasets",status_code=201)
    def create(body:dict):return call(lambda:manager.create(body))
    @router.get("/datasets/{dataset_id}/versions/{version}")
    def get(dataset_id:str,version:str):return call(lambda:manager.get(dataset_id,version))
    @router.post("/datasets/{dataset_id}/versions/{version}/freeze")
    def freeze(dataset_id:str,version:str):return call(lambda:manager.freeze(dataset_id,version))
    @router.post("/datasets/{dataset_id}/versions/{version}/ingest")
    def ingest(dataset_id:str,version:str,body:dict):return call(lambda:manager.ingest(dataset_id,version,body))
    @router.post("/datasets/{dataset_id}/versions/{version}/split")
    def split(dataset_id:str,version:str,body:dict):return call(lambda:manager.split(dataset_id,version,body))
    @router.post("/datasets/{dataset_id}/versions/{version}/new-version")
    def new_version(dataset_id:str,version:str,body:dict):return call(lambda:manager.new_version(dataset_id,version,body.get("version")))
    @router.get("/datasets/{dataset_id}/versions/{version}/export/{kind}")
    def export(dataset_id:str,version:str,kind:str):
        archive=call(lambda:manager.export(dataset_id,version,kind)); return FileResponse(archive,filename=archive.name,media_type="application/zip")
    return router
