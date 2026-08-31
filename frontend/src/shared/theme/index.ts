import { THEME } from '../constants';

export const theme = {
  colors: THEME.COLORS,
  spacing: THEME.SPACING,
  borderRadius: THEME.BORDER_RADIUS,

  // Component styles
  components: {
    button: {
      base: 'px-4 py-2 rounded-md font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2',
      variants: {
        primary: 'bg-blue-600 text-white hover:bg-blue-700 focus:ring-blue-500',
        secondary: 'bg-gray-200 text-gray-900 hover:bg-gray-300 focus:ring-gray-500',
        success: 'bg-green-600 text-white hover:bg-green-700 focus:ring-green-500',
        danger: 'bg-red-600 text-white hover:bg-red-700 focus:ring-red-500',
      },
      sizes: {
        sm: 'px-3 py-1.5 text-sm',
        md: 'px-4 py-2 text-base',
        lg: 'px-6 py-3 text-lg',
      },
    },

    input: {
      base: 'w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
      error: 'border-red-500 focus:ring-red-500',
    },

    card: {
      base: 'bg-white rounded-lg shadow-md border border-gray-200',
      header: 'px-6 py-4 border-b border-gray-200',
      body: 'px-6 py-4',
      footer: 'px-6 py-4 border-t border-gray-200 bg-gray-50',
    },

    modal: {
      overlay: 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50',
      content: 'bg-white rounded-lg shadow-xl max-w-md w-full mx-4',
      header: 'px-6 py-4 border-b border-gray-200',
      body: 'px-6 py-4',
      footer: 'px-6 py-4 border-t border-gray-200 flex justify-end space-x-3',
    },
  },

  // Layout
  layout: {
    sidebar: {
      width: '280px',
      collapsedWidth: '64px',
    },
    header: {
      height: '64px',
    },
  },

  // Spectrum visualization
  spectrum: {
    colors: {
      grid: '#e2e8f0',
      text: '#64748b',
      trace: '#3b82f6',
      marker: '#ef4444',
      background: '#ffffff',
    },
    fonts: {
      axis: '12px sans-serif',
      label: '14px sans-serif',
    },
  },

  // Breakpoints
  breakpoints: {
    sm: '640px',
    md: '768px',
    lg: '1024px',
    xl: '1280px',
  },
} as const;