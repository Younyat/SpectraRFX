import test from 'node:test';
import assert from 'node:assert/strict';
import {campaignContract,evaluateCampaignPolicy} from '../.ble-validation/campaignPolicy.js';

test('positive validation requires Visto ahora',()=>{
 assert.equal(evaluateCampaignPolicy({intent:'positive_target_validation',targetSelected:true,seenNow:false,operatorConfirmation:false}).allowed,false);
 assert.equal(evaluateCampaignPolicy({intent:'positive_target_validation',targetSelected:true,seenNow:true,operatorConfirmation:false}).allowed,true);
});

test('negative control requires declaration and confirmation',()=>{
 assert.equal(evaluateCampaignPolicy({intent:'negative_control',targetSelected:true,seenNow:false,operatorConfirmation:false}).allowed,false);
 assert.equal(evaluateCampaignPolicy({intent:'negative_control',targetSelected:true,seenNow:false,negativeControlType:'target_powered_off',operatorConfirmation:true}).allowed,true);
 assert.deepEqual(campaignContract('negative_control','target_powered_off',true),{campaign_intent:'negative_control',negative_control_type:'target_powered_off',operator_confirmation:true});
});

test('historical exploratory target is allowed without positive or negative claim',()=>{
 const result=evaluateCampaignPolicy({intent:'exploratory_target_search',targetSelected:true,seenNow:false,operatorConfirmation:false});
 assert.equal(result.allowed,true);
 assert.match(result.reason,/no será positivo ni negativo/);
});
