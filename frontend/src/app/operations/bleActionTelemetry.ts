import {failOperation,finishOperation,startOperation,updateOperation} from './operationTelemetry';

let pending:{id:string;created:number;claimed:boolean;timer:number}|null=null;
const cleanLabel=(value:string)=>value.replace(/\s+/g,' ').trim().slice(0,100)||'Acción BLE';

export const beginBleButtonAction=(label:string,target?:string)=>{
 if(pending){window.clearTimeout(pending.timer);finishOperation(pending.id,'Acción sustituida por una nueva pulsación')}
 const id=`ble-action:${Date.now()}:${Math.random().toString(16).slice(2)}`;
 startOperation({operationId:id,kind:'processing',title:cleanLabel(label),phase:'Pulsación recibida',progressPercent:5,target,estimatedTotalSeconds:null,detail:'Preparando la operación BLE'});
 const timer=window.setTimeout(()=>{if(pending?.id===id){finishOperation(id,'Acción de interfaz completada');pending=null}},1800);
 pending={id,created:Date.now(),claimed:false,timer};return id;
};

export const claimBleRequest=(url?:string)=>{
 if(!pending||pending.claimed||Date.now()-pending.created>2500||!String(url||'').includes('/api/ble/'))return null;
 pending.claimed=true;window.clearTimeout(pending.timer);updateOperation(pending.id,{phase:'Solicitud enviada al backend',progressPercent:25,detail:String(url)});return pending.id;
};
export const resolveBleRequest=(id:string|null,status?:number)=>{if(!id)return;updateOperation(id,{phase:'Respuesta recibida',progressPercent:85});finishOperation(id,`Backend respondió${status?` · HTTP ${status}`:''}`);if(pending?.id===id)pending=null};
export const rejectBleRequest=(id:string|null,message:string)=>{if(!id)return;failOperation(id,message);if(pending?.id===id)pending=null};
