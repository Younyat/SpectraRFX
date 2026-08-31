from fastapi import APIRouter,HTTPException
def build_ble_hybrid_router(manager):
    router=APIRouter(prefix="/ble/hybrid",tags=["ble-hybrid-controller"])
    def call(fn):
        try:return fn()
        except FileNotFoundError as e:raise HTTPException(404,"HYBRID_SESSION_NOT_FOUND") from e
        except ValueError as e:raise HTTPException(400,str(e)) from e
        except RuntimeError as e:raise HTTPException(409,str(e)) from e
    @router.post("/sessions",status_code=202)
    def start(body:dict):return call(lambda:manager.start(body))
    @router.get("/sessions")
    def sessions():return {"sessions":call(manager.list)}
    @router.get("/sessions/{session_id}")
    def status(session_id:str):return call(lambda:manager.get(session_id))
    @router.post("/sessions/{session_id}/stop")
    def stop(session_id:str):return call(lambda:manager.stop(session_id))
    @router.get("/sessions/{session_id}/results")
    def results(session_id:str):return call(lambda:manager.results(session_id))
    @router.get("/sessions/{session_id}/packets")
    def packets(session_id:str):return {"packets":call(lambda:manager.packets(session_id))}
    @router.get("/sessions/{session_id}/matches")
    def matches(session_id:str):return {"matches":call(lambda:manager.matches(session_id))}
    @router.get("/sessions/{session_id}/evidence")
    def evidence(session_id:str):return call(lambda:manager.evidence(session_id))
    @router.get("/sessions/{session_id}/scientific-summary")
    def scientific_summary(session_id:str):return call(lambda:manager.scientific_summary(session_id))
    return router
