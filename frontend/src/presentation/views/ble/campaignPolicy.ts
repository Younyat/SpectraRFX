export type CampaignIntent='positive_target_validation'|'negative_control'|'exploratory_target_search';
export type NegativeControlType='target_powered_off'|'target_physically_absent'|'other_device_substituted'|'ambient_only';

export const CAMPAIGN_INTENT_OPTIONS:{value:CampaignIntent;label:string;description:string}[]=[
 {value:'positive_target_validation',label:'Validación positiva del objetivo',description:'Exige advertising del objetivo en el último escaneo nativo. Enciende o despierta el sensor, desconéctalo de otros equipos y pulsa Buscar BLE ahora; no necesitas GATT, Dataset Studio ni análisis RF.'},
 {value:'negative_control',label:'Control negativo',description:'Exige declarar y confirmar una condición negativa.'},
 {value:'exploratory_target_search',label:'Búsqueda exploratoria',description:'Busca sin afirmar presencia ni ausencia física.'},
];

export const NEGATIVE_CONTROL_OPTIONS:{value:NegativeControlType;label:string}[]=[
 {value:'target_powered_off',label:'Objetivo apagado'},
 {value:'target_physically_absent',label:'Objetivo físicamente retirado'},
 {value:'other_device_substituted',label:'Objetivo sustituido por otro dispositivo'},
 {value:'ambient_only',label:'Sólo tráfico ambiental'},
];

export function evaluateCampaignPolicy(input:{intent:CampaignIntent;targetSelected:boolean;seenNow:boolean;negativeControlType?:NegativeControlType|'';operatorConfirmation:boolean}){
 if(input.intent==='positive_target_validation'){
  if(!input.targetSelected)return {allowed:false,reason:'Seleccione un objetivo específico para una validación positiva.'};
  if(!input.seenNow)return {allowed:false,reason:'La validación positiva está bloqueada: el último escaneo no recibió advertising de ese objetivo. Recargar historial no realiza un escaneo; enciende o despierta el sensor y pulsa Buscar BLE ahora.'};
 }
 if(input.intent==='negative_control'){
  if(!input.targetSelected)return {allowed:false,reason:'Seleccione el objetivo al que se aplica el control negativo.'};
  if(!input.negativeControlType)return {allowed:false,reason:'Declare la condición del control negativo antes de capturar.'};
  if(!input.operatorConfirmation)return {allowed:false,reason:'Confirme que la condición negativa se verificó físicamente antes de capturar.'};
 }
 return {allowed:true,reason:input.intent==='exploratory_target_search'&&!input.seenNow&&input.targetSelected?'Búsqueda exploratoria: el objetivo no está Visto ahora; el resultado no será positivo ni negativo.':''};
}

export function campaignContract(intent:CampaignIntent,negativeControlType:NegativeControlType|'',operatorConfirmation:boolean){
 return {
  campaign_intent:intent,
  negative_control_type:intent==='negative_control'?negativeControlType||undefined:undefined,
  operator_confirmation:intent==='negative_control'&&operatorConfirmation,
 };
}
