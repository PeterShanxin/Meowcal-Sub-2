export const state = {
  snapshot: null,
  config: null,
  languageCatalog: null,
  foundryStatus: null,
  selectedFeatureId: null,
  selectedSourceFileId: null,
  selectedTargetFileId: null,
  sourceSelectionMode: null,
  targetSelectionMode: null,
  overlayWindow: null,
  activeLanguagePicker: null,
  ui: {
    settingsOpen: false,
    manualView: null,
    resultsStepOverride: null,
  },
  bootstrap: {
    ready: false,
    loading: false,
  },
  languagePersistence: {
    saving: false,
    pendingKey: null,
    lastSavedKey: null,
  },
};
