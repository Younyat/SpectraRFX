import React from 'react';

export interface LabModuleDefinition {
  id: string;
  name: string;
  path: string;
  index?: boolean;
  aliases?: string[];
  icon: React.ComponentType<{ className?: string }>;
  element: React.ReactElement;
  enabled: boolean;
  showInNavigation: boolean;
  order: number;
  description: string;
}
