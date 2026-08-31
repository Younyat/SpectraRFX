export interface DatasetExample {session_id?:string;capture_id?:string;evidence_level?:string;inclusion_state?:string;crc_valid?:boolean}
export const summarizeExamples=(examples:DatasetExample[])=>({
 total:examples.length,
 crcValid:examples.filter(item=>item.crc_valid).length,
 included:examples.filter(item=>item.inclusion_state?.startsWith('INCLUDED')).length,
 excluded:examples.filter(item=>item.inclusion_state?.startsWith('EXCLUDED')).length,
 quarantined:examples.filter(item=>!item.inclusion_state?.startsWith('INCLUDED')).length,
 sessions:new Set(examples.map(item=>item.session_id).filter(Boolean)).size,
});
export interface DatasetSessionAudit {executedDurationSeconds:number;requiredDurationSeconds:number;metadataComplete:boolean;qualityClean:boolean;acceptedExamples:number;historicalImport:boolean}
export const summarizeProtocolProgress=(sessions:DatasetSessionAudit[],planned:number)=>({
 planned,
 executed:sessions.length,
 conformant:sessions.filter(item=>item.executedDurationSeconds===item.requiredDurationSeconds&&item.metadataComplete).length,
 historicalNonconformant:sessions.filter(item=>item.historicalImport&&!(item.executedDurationSeconds===item.requiredDurationSeconds&&item.metadataComplete)).length,
 accepted:sessions.filter(item=>item.executedDurationSeconds===item.requiredDurationSeconds&&item.metadataComplete&&item.qualityClean&&item.acceptedExamples>0).length,
});
export const splitScientificStatus=(acceptedExamples:number,integrityCheck:string)=>({splitIntegrityCheck:integrityCheck,splitStatus:acceptedExamples>0?'READY':'NOT_READY',trainingUsable:acceptedExamples>0,reason:acceptedExamples>0?null:'no_accepted_examples'});
export const splitHasLeakage=(split:Record<'train'|'validation'|'test',Record<string,string[]>>)=>{
 const groups=[Object.keys(split.train),Object.keys(split.validation),Object.keys(split.test)];
 return groups.some((left,index)=>groups.some((right,rightIndex)=>rightIndex>index&&left.some(key=>right.includes(key))));
};
