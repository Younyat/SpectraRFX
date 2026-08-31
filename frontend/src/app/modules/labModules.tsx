import { captureLabModule } from './capture-lab/module';
import { datasetBuilderModule } from './dataset-builder/module';
import { demodulationModule } from './demodulation/module';
import { liveDemodulationModule } from './live-demodulation/module';
import { wifiDashboardModule } from './wifi-dashboard/module';
import { inferenceModule } from './inference/module';
import { kiwiSdrMapModule } from './kiwisdr-map/module';
import { liveMonitorModule } from './live-monitor/module';
import { missionControlModule } from './mission-control/module';
import { modelsModule } from './models/module';
import { recordingsModule } from './recordings/module';
import { retrainingModule } from './retraining/module';
import { rfIntelligenceModule } from './rf-intelligence/module';
import { rfExperimentLabModule } from './rf-experiment-lab/module';
import { e6OracleStyleLabModule } from './e6-oracle-style-lab/module';
import { rfSignalUnderstandingModule } from './rf-signal-understanding/module';
import { settingsModule } from './settings/module';
import { trainingModule } from './training/module';
import { validationModule } from './validation/module';
import { waterfallModule } from './waterfall/module';
import { rfTerrainModule } from './rf-terrain/module';
import { aiResearchPluginModule } from './ai-research-plugin/module';
import { bleLabModule } from './ble-lab/module';
import { bleRffiStageOneModule } from './ble-rffi-stage-one/module';
import { blePacketAnalysisLabModule } from './ble-packet-analysis-lab/module';
import { bleRffiStudioModule } from './ble-rffi-studio/module';
import { bleScientificResultsModule } from './ble-scientific-results/module';
import { LabModuleDefinition } from './types';

export type { LabModuleDefinition } from './types';

export const labModules: LabModuleDefinition[] = [
  missionControlModule,
  liveMonitorModule,
  captureLabModule,
  datasetBuilderModule,
  trainingModule,
  retrainingModule,
  validationModule,
  inferenceModule,
  modelsModule,
  rfIntelligenceModule,
  rfExperimentLabModule,
  e6OracleStyleLabModule,
  rfSignalUnderstandingModule,
  waterfallModule,
  rfTerrainModule,
  recordingsModule,
  demodulationModule,
  wifiDashboardModule,
  bleLabModule,
  bleRffiStageOneModule,
  blePacketAnalysisLabModule,
  bleRffiStudioModule,
  bleScientificResultsModule,
  liveDemodulationModule,
  kiwiSdrMapModule,
  settingsModule,
  aiResearchPluginModule,
];

export const activeLabModules = labModules
  .filter((module) => module.enabled)
  .sort((left, right) => left.order - right.order);

export const navigationModules = activeLabModules.filter((module) => module.showInNavigation);

export const normalizeModulePath = (path: string) => (path === '/' ? '/' : path.replace(/^\//, ''));

export const findModuleByPath = (pathname: string) => activeLabModules.find((module) => [module.path, ...(module.aliases ?? [])].includes(pathname));

export const moduleRoutes = activeLabModules.flatMap((module) => {
  const routes = module.index
    ? [{ index: true as const, element: module.element }]
    : [{ path: normalizeModulePath(module.path), element: module.element }];
  const aliasRoutes = (module.aliases ?? []).map((alias) => ({ path: normalizeModulePath(alias), element: module.element }));
  return [...routes, ...aliasRoutes];
});
