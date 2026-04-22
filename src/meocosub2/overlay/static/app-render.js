import { dom } from "./app-dom.js";
import { state } from "./app-state.js";
import { TAURI, apiUrl } from "./app-api.js";
import {
  assrtCoverageHint,
  currentLanguageValue,
  deriveOcrLanguage,
  isChineseFamily,
  languageLabel,
  normalizeLanguageCode,
  providerConfig,
  updateDerivedOcrDisplay,
} from "./app-language.js";

export function selectionValue(value) {
  if (value == null || value === "") {
    return null;
  }
  return String(value);
}

export function sameSelectionValue(left, right) {
  return selectionValue(left) === selectionValue(right);
}

export function numericSelectionValue(value) {
  const normalized = selectionValue(value);
  return normalized && /^\d+$/.test(normalized) ? Number(normalized) : null;
}

export function matchSelectionId(match) {
  if (!match) {
    return null;
  }
  return selectionValue(match.matchId ?? match.id);
}

export function resultSelectionId(result) {
  if (!result) {
    return null;
  }
  return selectionValue(result.resultId ?? result.fileId ?? result.id);
}

function providerLabelText(entry) {
  return entry?.providerLabel || entry?.provider_label || entry?.provider || "";
}

function providerLabelsForMatch(match) {
  if (Array.isArray(match?.providerLabels) && match.providerLabels.length) {
    return match.providerLabels;
  }
  if (Array.isArray(match?.providers) && match.providers.length) {
    return match.providers;
  }
  return match?.providerLabel ? [match.providerLabel] : [];
}

function resultMatchesFeature(result, featureId) {
  const numericFeatureId = numericSelectionValue(featureId);
  if (numericFeatureId == null) {
    return true;
  }
  return [result.parentFeatureId, result.featureId].some((value) => Number(value) === numericFeatureId);
}

export function resultMatchesSelectedMatch(result, matchId) {
  if (!matchId) {
    return true;
  }
  if (result.matchId != null) {
    return sameSelectionValue(result.matchId, matchId);
  }
  return resultMatchesFeature(result, matchId);
}

export function currentFeatureId(snapshot) {
  return (
    state.selectedFeatureId ??
    selectionValue(snapshot?.selected_match_id) ??
    selectionValue(snapshot?.selected_feature_id) ??
    null
  );
}

export function selectedSourceResultId(snapshot) {
  return state.selectedSourceFileId ?? selectionValue(snapshot?.selected_source_result_id) ?? selectionValue(snapshot?.selected_source_file_id);
}

export function selectedTargetResultId(snapshot) {
  return state.selectedTargetFileId ?? selectionValue(snapshot?.selected_target_result_id) ?? selectionValue(snapshot?.selected_target_file_id);
}

export function currentSourceSelectionMode(snapshot) {
  if (state.sourceSelectionMode) {
    return state.sourceSelectionMode;
  }
  if (snapshot?.prepared_session?.session_mode) {
    return snapshot.prepared_session.session_mode === "ocr_fallback" ? "ocr_fallback" : "subtitle";
  }
  return "subtitle";
}

function currentResultsStep(snapshot) {
  if (!currentFeatureId(snapshot)) {
    return "title";
  }
  if (!selectedSourceResultId(snapshot) && currentSourceSelectionMode(snapshot) !== "ocr_fallback") {
    return "source";
  }
  return "target";
}

export function currentVisibleResultsStep(snapshot) {
  const forcedStep = state.ui.resultsStepOverride;
  if (forcedStep === "source" && currentFeatureId(snapshot)) {
    return "source";
  }
  if (forcedStep === "title") {
    return "title";
  }
  return currentResultsStep(snapshot);
}

export function currentTargetSelectionMode(snapshot) {
  if (state.targetSelectionMode) {
    return state.targetSelectionMode;
  }
  if (selectedTargetResultId(snapshot)) {
    return "file";
  }
  if (snapshot?.prepared_session) {
    return snapshot.prepared_session.target_match_mode === "subtitle_file" ? "file" : "local";
  }
  return null;
}

function navButtons() {
  return Array.from(document.querySelectorAll("[data-view-target]"));
}

function availableShellView(snapshot) {
  if (state.ui.settingsOpen) {
    return "settings";
  }
  if (snapshot.status === "running" || snapshot.status === "preparing" || snapshot.status === "stopping" || snapshot.prepared_session) {
    return "session";
  }
  if ((snapshot.search_matches || []).length || (snapshot.search_results || []).length) {
    return "results";
  }
  return "dashboard";
}

function currentShellView(snapshot) {
  if (state.ui.settingsOpen) {
    return "settings";
  }

  const preferred = state.ui.manualView;
  if (preferred === "dashboard") {
    return "dashboard";
  }
  if (preferred === "results" && ((snapshot.search_matches || []).length || (snapshot.search_results || []).length)) {
    return "results";
  }
  if (preferred === "session" && (snapshot.prepared_session || snapshot.status === "running" || snapshot.status === "preparing" || snapshot.status === "stopping")) {
    return "session";
  }
  return availableShellView(snapshot);
}

function statusLabel(status) {
  const labels = {
    idle: "Idle",
    searching: "Searching",
    preparing: "Preparing",
    running: "Running",
    stopping: "Stopping",
    error: "Error",
  };
  return labels[status] || "Idle";
}

function sessionHeadline(snapshot, selectedSource, selectedTarget) {
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
  if (snapshot.status === "searching") {
    return snapshot.title ? `Finding subtitle sources for ${snapshot.title}` : "Finding subtitle matches";
  }
  if (snapshot.status === "preparing") {
    return "Preparing your subtitle session";
  }
  if (snapshot.status === "running") {
    return "Live sync is active";
  }
  if (snapshot.status === "stopping") {
    return "Stopping live sync";
  }
  if (snapshot.error_message) {
    return "Something needs attention";
  }
  if (snapshot.prepared_session) {
    return snapshot.prepared_session.session_mode === "ocr_fallback"
      ? "OCR fallback session prepared. Start sync when playback begins."
      : "Session prepared. Start sync when the video is ready.";
  }
  if (selectedSource && !targetSelectionMode) {
    return "Choose a target subtitle or confirm local translation";
  }
  if (selectedSource && selectedTarget != null) {
    return "Subtitle pair selected. Prepare the session next.";
  }
  if (selectedSource) {
    return "Source selected. Keep local translation or choose a target subtitle.";
  }
  if ((snapshot.search_matches || []).length) {
    return "Choose a matched title, then pick subtitles from the merged source list or use OCR fallback.";
  }
  if ((snapshot.search_results || []).length) {
    return "Choose the subtitle pair for this session.";
  }
  return "Search for a title to begin";
}

function sessionMessage(snapshot, selectedSource, selectedTarget) {
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
  if (snapshot.error_message) {
    return snapshot.error_message;
  }
  if (snapshot.warning_message) {
    return snapshot.warning_message;
  }
  if (snapshot.status === "running") {
    return snapshot.prepared_session?.session_mode === "ocr_fallback"
      ? "Live OCR text is being translated and aligned against target subtitles when possible."
      : "The OCR loop is matching on-screen subtitles and sending lines to the overlay.";
  }
  if (snapshot.prepared_session) {
    return snapshot.prepared_session.session_mode === "ocr_fallback"
      ? "Foundry-backed OCR fallback is ready. Open the overlay and start sync when playback begins."
      : "Your subtitle files are ready. Open the overlay and start sync when playback begins.";
  }
  if (selectedSource && !targetSelectionMode) {
    return "Choose a target subtitle or click local translation to confirm the target step.";
  }
  if ((snapshot.search_matches || []).length) {
    return "Review the matched titles below. Provider badges show where each subtitle came from, and OCR fallback remains available.";
  }
  if ((snapshot.search_results || []).length) {
    return "Review the merged results below. The source subtitle choice drives the rest of the flow.";
  }
  return "Ready for a title search.";
}

function progressSummary(snapshot, selectedSource) {
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
  if (snapshot.progress?.message) {
    return snapshot.progress.message;
  }
  if (snapshot.prepared_session) {
    return snapshot.prepared_session.session_mode === "ocr_fallback"
      ? "Prepared OCR fallback session will translate live OCR and optionally align against target subtitles."
      : "Prepared session is ready for the next viewing run.";
  }
  if (selectedSource && !targetSelectionMode) {
    return "Confirm the target side before preparing the session.";
  }
  if (selectedSource) {
    return "Prepare the session once the subtitle choice looks right.";
  }
  if ((snapshot.search_matches || []).length) {
    return "Pick a title first, then choose source subtitles from the merged source list or OCR fallback.";
  }
  if ((snapshot.search_results || []).length) {
    return "Select a source subtitle and confirm the target side.";
  }
  return "Search and choose subtitle files to begin.";
}

function renderShellChrome(view, snapshot, selectedMatch) {
  const sourceLanguage = snapshot.source_language || currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput);
  const targetLanguage = snapshot.target_language || currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput);

  dom.appShell?.setAttribute("data-view", view);
  document.body?.setAttribute("data-view", view);
  document.body.dataset.view = view;

  for (const button of navButtons()) {
    const target = button.dataset.viewTarget;
    const active = target === view;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  }

  const resultsReady = Boolean((snapshot.search_matches || []).length || (snapshot.search_results || []).length);
  const sessionReady = Boolean(snapshot.prepared_session || snapshot.status === "running" || snapshot.status === "preparing" || snapshot.status === "stopping");
  for (const button of navButtons()) {
    const target = button.dataset.viewTarget;
    if (target === "results") {
      button.disabled = !resultsReady && view !== "results";
    } else if (target === "session") {
      button.disabled = !sessionReady && view !== "session";
    } else {
      button.disabled = false;
    }
  }

  if (view === "results") {
    dom.heroEyebrow.textContent = "Search Results For";
    dom.heroTitleMain.textContent = selectedMatch?.displayLabel || snapshot.title || "Search results ";
    dom.heroTitleAccent.textContent = "ready";
    dom.heroSubcopy.textContent = "Select source and target files to begin your synchronization session.";
  } else if (view === "session") {
    dom.heroEyebrow.textContent = "Session Status";
    dom.heroTitleMain.textContent = "Session ";
    dom.heroTitleAccent.textContent = snapshot.status === "running" ? "live" : "ready";
    dom.heroSubcopy.textContent = sessionMessage(snapshot, selectedSourceResultId(snapshot), selectedTargetResultId(snapshot));
  } else {
    dom.heroEyebrow.textContent = "Console Mode";
    dom.heroTitleMain.textContent = "What do you want to ";
    dom.heroTitleAccent.textContent = "watch?";
    dom.heroSubcopy.textContent = "Search by title first, pick the best subtitle pair, then prepare a session before starting live sync.";
  }

  dom.dashboardSummaryMatches.textContent = String((snapshot.search_matches || []).length);
  dom.dashboardSummaryResults.textContent = String((snapshot.search_results || []).length);
  dom.dashboardSummarySession.textContent = statusLabel(snapshot.status || "idle");

  dom.sessionViewTitle.textContent = snapshot.status === "running" ? "Session Live" : "Session Ready";
  dom.sessionViewCopy.textContent =
    snapshot.prepared_session && !hasCaptureRegion()
      ? "Session prepared. Select the subtitle capture area next, then start sync."
      : sessionMessage(snapshot, selectedSourceResultId(snapshot), selectedTargetResultId(snapshot));
  dom.sessionPreviewLabel.textContent = snapshot.prepared_session?.session_mode === "ocr_fallback" ? "OCR Fallback" : "Subtitle Pair";
  dom.sessionFoundryState.textContent = dom.foundryStatusChip?.textContent || "Unchecked";
  dom.sessionFoundryNote.textContent = dom.foundryStatusNote?.textContent || "Waiting for status probe.";
  dom.sessionOcrState.textContent = dom.ocrLanguageDisplay?.textContent || "Follows source language";
  dom.sessionOcrNote.textContent = dom.ocrLanguageNote?.textContent || "Capture language follows the selected source language.";
  dom.sessionCaptureState.textContent = document.getElementById("capture-region-input")?.value?.trim() || "Not set";

  dom.footerSessionStatus.textContent = `Session: ${statusLabel(snapshot.status || "idle")}`;
  dom.footerBackendStatus.textContent = `Backend: ${state.bootstrap.ready ? "Connected" : "Starting"}`;
  dom.footerOcrStatus.textContent = `OCR: ${dom.ocrLanguageDisplay?.textContent || "Follows source language"}`;
  void sourceLanguage;
  void targetLanguage;
}

function createElement(tagName, options = {}) {
  const element = document.createElement(tagName);
  if (options.className) {
    element.className = options.className;
  }
  if (options.text != null) {
    element.textContent = String(options.text);
  }
  if (options.attrs) {
    for (const [name, value] of Object.entries(options.attrs)) {
      if (value != null) {
        element.setAttribute(name, String(value));
      }
    }
  }
  if (options.dataset) {
    for (const [name, value] of Object.entries(options.dataset)) {
      if (value != null) {
        element.dataset[name] = String(value);
      }
    }
  }
  return element;
}

function appendBadge(container, text, className = "result-badge") {
  container.append(createElement("span", { className, text }));
}

function providerBadgeClass(provider) {
  const normalized = (provider || "source").toString().trim().toLowerCase().replace(/[^a-z0-9]+/g, "-");
  return `result-badge provider-badge provider-${normalized}`;
}

function buildResultCard({
  resultId = "",
  selected = false,
  kind = "",
  title,
  tag = "",
  badges = [],
  fileText,
  footText,
  tagName = "button",
  className = "",
  attrs = {},
  dataset = {},
}) {
  const classes = ["result-card"];
  if (className) {
    classes.push(className);
  }
  if (tagName !== "button") {
    classes.push("result-card-static");
  }
  if (selected) {
    classes.push("selected");
  }
  const cardAttrs = { ...attrs };
  if (tagName === "button") {
    cardAttrs.type = cardAttrs.type || "button";
  }
  const card = createElement(tagName, {
    className: classes.join(" "),
    attrs: cardAttrs,
    dataset: { resultId, kind: kind || undefined, ...dataset },
  });

  const top = createElement("div", { className: "result-card-top" });
  top.append(createElement("h4", { className: "result-card-title", text: title }));
  if (tag) {
    top.append(createElement("span", { className: "result-card-tag", text: tag }));
  }
  card.append(top);

  if (badges.length) {
    const meta = createElement("div", { className: "result-card-meta" });
    for (const badge of badges) {
      if (typeof badge === "string") {
        appendBadge(meta, badge);
      } else if (badge && typeof badge === "object") {
        appendBadge(meta, badge.text, badge.className || "result-badge");
      }
    }
    card.append(meta);
  }

  if (fileText) {
    card.append(createElement("p", { className: "result-card-file", text: fileText }));
  }
  if (footText) {
    card.append(createElement("p", { className: "result-card-foot", text: footText }));
  }
  return card;
}

function buildTitleMatchCard(match, selected = false, options = {}) {
  const { tagName = "button", className = "", attrs = {}, dataset = {} } = options;
  const classes = ["title-match-card"];
  if (className) {
    classes.push(className);
  }
  if (tagName !== "button") {
    classes.push("result-card-static");
  }
  if (selected) {
    classes.push("selected");
  }
  const cardAttrs = { ...attrs };
  if (tagName === "button") {
    cardAttrs.type = cardAttrs.type || "button";
  }
  const card = createElement(tagName, {
    className: classes.join(" "),
    attrs: cardAttrs,
    dataset: { matchId: matchSelectionId(match) || match.id || "", ...dataset },
  });
  const top = createElement("div", { className: "result-card-top" });
  top.append(createElement("h4", { className: "result-card-title", text: match.displayLabel || match.title }));
  if (selected) {
    top.append(createElement("span", { className: "result-card-tag", text: "Selected" }));
  }
  card.append(top);
  const meta = createElement("div", { className: "result-card-meta" });
  appendBadge(meta, match.mediaType || "title");
  appendBadge(meta, `${(match.subtitlesCount || 0).toLocaleString()} subtitle files`);
  if (match.providerCount || providerLabelsForMatch(match).length) {
    appendBadge(meta, `${(match.providerCount || providerLabelsForMatch(match).length).toLocaleString()} sources`);
  }
  for (const label of providerLabelsForMatch(match).slice(0, 3)) {
    appendBadge(meta, label, providerBadgeClass(label));
  }
  card.append(meta);
  card.append(createElement("p", { className: "result-card-foot", text: "Use this title to scope source and target subtitle choices across enabled sources." }));
  return card;
}

function resultDownloadFootText(result) {
  const providerLabel = providerLabelText(result);
  return `${result.downloadCount.toLocaleString()} downloads${providerLabel ? ` via ${providerLabel}` : ""}`;
}

function sourceResultBadges(result, requestedSourceLanguage = "") {
  const providerLabel = providerLabelText(result);
  const badges = providerLabel
    ? [{ text: providerLabel, className: providerBadgeClass(result.providerLabel || result.provider) }, languageLabel(result.language)]
    : [languageLabel(result.language)];
  if (normalizeLanguageCode(result.language) === normalizeLanguageCode(requestedSourceLanguage)) {
    badges.push("Exact language");
  }
  if (
    requestedSourceLanguage &&
    normalizeLanguageCode(result.language) !== normalizeLanguageCode(requestedSourceLanguage) &&
    isChineseFamily(requestedSourceLanguage) &&
    isChineseFamily(result.language)
  ) {
    badges.push("Chinese-family fallback");
  }
  return badges;
}

function targetResultBadges(result) {
  const providerLabel = providerLabelText(result);
  return providerLabel
    ? [{ text: providerLabel, className: providerBadgeClass(result.providerLabel || result.provider) }, languageLabel(result.language)]
    : [languageLabel(result.language)];
}

function renderTitleMatches(matches, selectedFeatureId) {
  if (!matches.length) {
    dom.titleMatchResults.className = "title-match-results empty-state";
    dom.titleMatchResults.textContent = "Search to load matched shows and movies.";
    dom.titleMatchCount.textContent = "0 titles";
    return;
  }

  dom.titleMatchCount.textContent = `${matches.length} titles`;
  dom.titleMatchResults.className = "title-match-results";
  dom.titleMatchResults.replaceChildren(
    ...matches.map((match) => buildTitleMatchCard(match, sameSelectionValue(matchSelectionId(match), selectedFeatureId))),
  );
}

function buildSearchResultSummary(selectedMatch, sourceResults, targetResults, sourceSelectionMode, sourceLanguage) {
  const targetSelectionMode = currentTargetSelectionMode(state.snapshot);
  const coverageHint = assrtCoverageHint(sourceLanguage);
  if (!selectedMatch) {
    return "Pick a matched title first, then choose subtitles or OCR fallback.";
  }
  if (!sourceResults.length && !targetResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} matched, but no subtitle files fit the selected languages. OCR fallback is available.${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!sourceResults.length && sourceSelectionMode === "ocr_fallback") {
    return `${selectedMatch.displayLabel || selectedMatch.title} has no ${languageLabel(sourceLanguage)} source subtitle. OCR fallback is selected${targetResults.length ? " and can still align against target subtitles." : "."}${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!sourceResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} has no ${languageLabel(sourceLanguage)} source subtitle. Select OCR fallback to continue.${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!targetSelectionMode) {
    return `${selectedMatch.displayLabel || selectedMatch.title} is ready on the source side. Pick a target subtitle or click local translation to confirm the target step.${coverageHint ? ` ${coverageHint}` : ""}`;
  }
  if (!targetResults.length) {
    return `${selectedMatch.displayLabel || selectedMatch.title} has ${sourceResults.length} source subtitle choices across enabled sources. Target can fall back to local translation.`;
  }
  return `${selectedMatch.displayLabel || selectedMatch.title}: ${sourceResults.length} source matches and ${targetResults.length} target matches ready.`;
}

function renderSourceResults(container, results, selectedId, requestedSourceLanguage = "", options = {}) {
  const { selectedMatch = null, sourceSelectionMode = "subtitle" } = options;
  if (!results.length && selectedMatch) {
    const coverageHint = assrtCoverageHint(requestedSourceLanguage);
    container.className = "result-list";
    container.replaceChildren(
      buildResultCard({
        resultId: "",
        kind: "ocr-fallback",
        selected: sourceSelectionMode === "ocr_fallback",
        title: "Use OCR source language",
        tag: "Fallback",
        badges: [languageLabel(requestedSourceLanguage), "No source file"],
        fileText: `No source subtitle file matches this title and language.${coverageHint ? ` ${coverageHint}` : ""} Use OCR plus live AI translation instead.`,
        footText: "If a target subtitle is selected, the live translation will try to align against it.",
      }),
    );
    return;
  }

  if (!results.length) {
    container.className = "result-list empty-state";
    container.textContent = "No results available for this language.";
    return;
  }

  container.className = "result-list";
  container.replaceChildren(
    ...results.map((result, index) => {
      return buildResultCard({
        resultId: resultSelectionId(result),
        selected: sameSelectionValue(resultSelectionId(result), selectedId) && sourceSelectionMode !== "ocr_fallback",
        title: result.displayLabel || result.title,
        tag: index === 0 ? "Recommended" : "",
        badges: sourceResultBadges(result, requestedSourceLanguage),
        fileText: result.fileName,
        footText: resultDownloadFootText(result),
      });
    }),
  );
}

function renderTargetResults(container, results, selectedId, sourceSelectionMode = "subtitle", targetSelectionMode = null) {
  container.className = "result-list";
  container.replaceChildren(
    buildResultCard({
      resultId: "",
      kind: "local",
      selected: targetSelectionMode === "local",
      title: "Use local translation",
      tag: targetSelectionMode === "local" ? "Confirmed" : "Fallback",
      badges: ["No target file"],
      fileText:
        sourceSelectionMode === "ocr_fallback"
          ? "Prepare the session by translating live OCR text directly into the target language."
          : "Prepare the session by translating the selected source subtitle locally.",
      footText: targetSelectionMode === "local" ? "Local translation confirmed for this session." : "Click to confirm local translation when no matching target subtitle looks trustworthy.",
    }),
    ...results.map((result, index) =>
      buildResultCard({
        resultId: resultSelectionId(result),
        selected: sameSelectionValue(resultSelectionId(result), selectedId) && targetSelectionMode === "file",
        title: result.displayLabel || result.title,
        tag: sameSelectionValue(resultSelectionId(result), selectedId) && targetSelectionMode === "file" ? "Selected" : index === 0 ? "Best match" : "",
        badges: targetResultBadges(result),
        fileText: result.fileName,
        footText: resultDownloadFootText(result),
      }),
    ),
  );
}

function buildResultsSummaryRow({ label, value, meta = "", status = "", statusKind = "pending", badges = [] }) {
  const row = createElement("section", { className: `results-summary-row is-${statusKind}` });
  const top = createElement("div", { className: "results-summary-row-top" });
  top.append(createElement("p", { className: "results-summary-row-label", text: label }));
  if (status) {
    top.append(createElement("span", { className: `results-summary-row-status is-${statusKind}`, text: status }));
  }
  row.append(top);
  row.append(createElement("p", { className: "results-summary-row-value", text: value }));
  if (meta) {
    row.append(createElement("p", { className: "results-summary-row-meta", text: meta }));
  }
  if (badges.length) {
    const badgeRow = createElement("div", { className: "results-summary-badges" });
    for (const badge of badges) {
      if (typeof badge === "string") {
        appendBadge(badgeRow, badge, "result-badge results-summary-badge");
      } else if (badge?.text) {
        appendBadge(badgeRow, badge.text, badge.className || "result-badge results-summary-badge");
      }
    }
    row.append(badgeRow);
  }
  return row;
}

function renderResultsFlow(resultsStep, sourceSelectionMode, targetSelectionMode) {
  if (!dom.resultsFlow) {
    return;
  }

  const steps = Array.from(dom.resultsFlow.querySelectorAll("[data-flow-step]"));
  const completed = {
    title: resultsStep !== "title",
    source: resultsStep === "target" || sourceSelectionMode === "ocr_fallback",
    target: Boolean(targetSelectionMode),
  };

  for (const step of steps) {
    const stepKey = step.dataset.flowStep;
    const isCurrent = stepKey === resultsStep;
    const isComplete = completed[stepKey] && !isCurrent;
    step.classList.toggle("is-current", isCurrent);
    step.classList.toggle("is-complete", isComplete);
    step.classList.toggle("is-pending", !isCurrent && !isComplete);
  }

  const dividers = Array.from(dom.resultsFlow.querySelectorAll(".results-flow-divider"));
  if (dividers[0]) {
    dividers[0].classList.toggle("is-complete", completed.title);
  }
  if (dividers[1]) {
    dividers[1].classList.toggle("is-complete", completed.source);
  }
}

function renderResultsSelectionSummary({
  snapshot,
  resultsStep,
  selectedMatch,
  selectedSourceResult,
  selectedTargetResult,
  searchMatches,
  filteredResults,
  sourceResults,
  sourceSelectionMode,
  targetSelectionMode,
  sourceLanguage,
  targetLanguage,
}) {
  if (!dom.resultsSelectionSummary) {
    return;
  }

  const hasSearchState = Boolean(snapshot.title || searchMatches.length || filteredResults.length);
  if (!hasSearchState) {
    dom.resultsSelectionSummary.className = "results-selection-summary empty-state";
    dom.resultsSelectionSummary.textContent = "Search to review the active title and subtitle choices.";
    return;
  }

  let summaryRow;
  if (resultsStep === "title") {
    const titleBadges = selectedMatch
      ? [
          selectedMatch.mediaType || "title",
          `${(selectedMatch.subtitlesCount || 0).toLocaleString()} subtitle files`,
          `${(selectedMatch.providerCount || providerLabelsForMatch(selectedMatch).length).toLocaleString()} sources`,
        ].filter(Boolean)
      : [`${searchMatches.length} matches ready`];
    summaryRow = buildResultsSummaryRow({
      label: "Title",
      value: selectedMatch?.displayLabel || selectedMatch?.title || "Pick a matched title",
      meta: selectedMatch
        ? snapshot.title && selectedMatch.displayLabel !== snapshot.title
          ? `Search: ${snapshot.title}`
          : "Matched title selected"
        : "Choose the best title from the right pane to continue.",
      status: selectedMatch ? "Selected" : "Pending",
      statusKind: selectedMatch ? "selected" : "pending",
      badges: titleBadges.slice(0, 3),
    });
  } else if (resultsStep === "source") {
    const sourceBadges = selectedSourceResult
      ? sourceResultBadges(selectedSourceResult, sourceLanguage).slice(0, 2)
      : [languageLabel(sourceLanguage)];
    summaryRow = buildResultsSummaryRow({
      label: "Source",
      value: selectedSourceResult
        ? selectedSourceResult.displayLabel || selectedSourceResult.title
        : sourceSelectionMode === "ocr_fallback"
          ? "OCR source fallback"
          : "Choose a source subtitle",
      meta: selectedSourceResult
        ? `Title: ${selectedMatch?.displayLabel || selectedMatch?.title || snapshot.title || "Selected match"}`
        : sourceSelectionMode === "ocr_fallback"
          ? `Title: ${selectedMatch?.displayLabel || selectedMatch?.title || snapshot.title || "Selected match"}`
          : "Select a source subtitle from the right pane.",
      status: selectedSourceResult ? "Selected" : sourceSelectionMode === "ocr_fallback" ? "Fallback" : "Pending",
      statusKind: selectedSourceResult ? "selected" : sourceSelectionMode === "ocr_fallback" ? "fallback" : "pending",
      badges: sourceBadges,
    });
  } else {
    const targetBadges = selectedTargetResult
      ? targetResultBadges(selectedTargetResult).slice(0, 2)
      : [languageLabel(targetLanguage)];
    summaryRow = buildResultsSummaryRow({
      label: "Target",
      value: selectedTargetResult
        ? selectedTargetResult.displayLabel || selectedTargetResult.title
        : targetSelectionMode === "local"
          ? "Local translation"
          : "Choose a target subtitle",
      meta: selectedSourceResult
        ? `Source: ${selectedSourceResult.displayLabel || selectedSourceResult.title}`
        : sourceSelectionMode === "ocr_fallback"
          ? "Source: OCR fallback"
          : "Confirm the target side to enable session prep.",
      status: selectedTargetResult ? "Selected" : targetSelectionMode === "local" ? "Confirmed" : "Pending",
      statusKind: selectedTargetResult ? "selected" : targetSelectionMode === "local" ? "confirmed" : "pending",
      badges: targetBadges,
    });
  }

  dom.resultsSelectionSummary.className = "results-selection-summary";
  dom.resultsSelectionSummary.replaceChildren(summaryRow);
}

function renderSessionSummary(preparedSession) {
  if (!preparedSession) {
    dom.preparedSession.className = "session-summary empty-state";
    dom.preparedSession.textContent = "No session has been prepared yet.";
    dom.sessionBadge.textContent = "None";
    return;
  }

  dom.sessionBadge.textContent = preparedSession.session_id;
  dom.preparedSession.className = "session-summary";
  const summary = createElement("div", { className: "session-summary-stack" });
  const hero = createElement("div", { className: "session-summary-hero" });
  hero.append(createElement("p", { className: "session-summary-label", text: preparedSession.title }));
  hero.append(
    createElement("h3", {
      className: "session-summary-title",
      text: preparedSession.session_mode === "ocr_fallback" ? "OCR Fallback Session" : "Subtitle Pair Ready",
    }),
  );
  hero.append(
    createElement("p", {
      className: "session-summary-copy",
      text:
        preparedSession.session_mode === "ocr_fallback"
          ? "Live OCR will translate on-screen text and align against a target file when possible."
          : "The selected subtitle files are calibrated and ready for the next viewing run.",
    }),
  );
  summary.append(hero);

  const chips = createElement("div", { className: "session-summary-chip-row" });
  chips.append(createElement("span", { className: "session-summary-chip", text: preparedSession.source_provider_label || preparedSession.sourceProviderLabel || "OCR source" }));
  chips.append(createElement("span", { className: "session-summary-chip", text: preparedSession.target_provider_label || preparedSession.targetProviderLabel || "Local translation" }));
  chips.append(createElement("span", { className: "session-summary-chip", text: preparedSession.session_id }));
  summary.append(chips);

  const grid = createElement("dl");
  const modeLabelMap = {
    subtitle_file: "Matched target subtitle",
    local_translation: "Local translation",
    target_subtitle_match: "OCR fallback + target subtitle match",
    direct_translation: "OCR fallback + direct AI translation",
  };
  const rows = [
    ["Title", preparedSession.title],
    ["Session Mode", preparedSession.session_mode === "ocr_fallback" ? "OCR fallback" : "Subtitle pair"],
    [
      "Source Provider",
      preparedSession.source_provider_label || preparedSession.sourceProviderLabel || "OCR source language",
    ],
    ["Source File", preparedSession.source_file_name || "OCR source language"],
    [
      "Target Provider",
      preparedSession.target_provider_label || preparedSession.targetProviderLabel || "Local translation",
    ],
    ["Target File", preparedSession.target_file_name || "Generated via translation"],
    [
      "Resolved Source",
      `${preparedSession.resolved_source_language}${preparedSession.source_language_mode !== "exact" ? " (fallback)" : ""}`,
    ],
    ["Source Lines", preparedSession.source_line_count],
    ["Translated Lines", preparedSession.translated_line_count],
    ["Mode", modeLabelMap[preparedSession.target_match_mode] || "Matched target subtitle"],
  ];
  for (const [term, description] of rows) {
    grid.append(createElement("dt", { text: term }));
    grid.append(createElement("dd", { text: description }));
  }
  summary.append(grid);
  dom.preparedSession.replaceChildren(summary);
}

function regionToString(region) {
  return Array.isArray(region) ? region.join(",") : "";
}

export function parseRegion(value) {
  if (!value.trim()) {
    return [];
  }
  return value
    .split(",")
    .map((part) => Number(part.trim()))
    .filter((item) => Number.isFinite(item));
}

export function hasCaptureRegion() {
  const region = parseRegion(document.getElementById("capture-region-input")?.value || "");
  return region.length === 4 && region[2] > 0 && region[3] > 0;
}

export function applyStylePreview(overlay) {
  if (!overlay) {
    return;
  }

  const root = document.documentElement;
  root.style.setProperty("--overlay-font-size", `${overlay.fontSize}px`);
  root.style.setProperty("--overlay-font-family", overlay.fontFamily);
  root.style.setProperty("--overlay-text-color", overlay.textColor);
  root.style.setProperty("--overlay-bg-color", overlay.bgColor);
  root.style.setProperty("--overlay-radius", `${overlay.radiusPx}px`);
  root.style.setProperty("--overlay-padding", `${overlay.paddingPx}px`);
  root.style.setProperty("--overlay-max-width", `${overlay.maxWidthVw}vw`);
  root.style.setProperty("--overlay-blur", `${overlay.blurPx}px`);
  root.style.setProperty("--overlay-shadow-strength", overlay.shadowStrength);
  root.style.setProperty("--overlay-offset", `${overlay.offsetPct}%`);
  root.style.setProperty("--overlay-animation-ms", `${overlay.animationMs}ms`);
  const previewShell = document.getElementById("preview-shell");
  if (previewShell) {
    previewShell.dataset.position = overlay.position || "bottom";
  }
}

export function fillConfigForm(config) {
  const { capture, translation, overlay } = config;
  const subtitleSources = providerConfig(config);
  dom.opensubtitlesEnabledInput.checked = subtitleSources.opensubtitles.enabled !== false;
  dom.opensubtitlesApiKeyInput.value = subtitleSources.opensubtitles.apiKey || "";
  dom.opensubtitlesOrgFallbackInput.checked = subtitleSources.opensubtitles.enableOrgFallback === true;
  dom.subdlEnabledInput.checked = subtitleSources.subdl.enabled !== false;
  dom.assrtEnabledInput.checked = subtitleSources.assrt.enabled === true;
  dom.assrtTokenInput.value = subtitleSources.assrt.token || "";
  document.getElementById("translation-endpoint-input").value = translation.endpoint || "";
  document.getElementById("translation-model-input").value = translation.model || "";
  document.getElementById("capture-interval-input").value = capture.intervalMs ?? 1500;
  document.getElementById("capture-region-input").value = regionToString(capture.region);
  document.getElementById("overlay-theme-input").value = overlay.theme;
  document.getElementById("overlay-position-input").value = overlay.position;
  document.getElementById("overlay-font-family-input").value = overlay.fontFamily;
  document.getElementById("overlay-font-size-input").value = overlay.fontSize;
  document.getElementById("overlay-text-color-input").value = overlay.textColor;
  document.getElementById("overlay-bg-color-input").value = overlay.bgColor;
  document.getElementById("overlay-radius-input").value = overlay.radiusPx;
  document.getElementById("overlay-padding-input").value = overlay.paddingPx;
  document.getElementById("overlay-max-width-input").value = overlay.maxWidthVw;
  document.getElementById("overlay-blur-input").value = overlay.blurPx;
  document.getElementById("overlay-shadow-input").value = overlay.shadowStrength;
  document.getElementById("overlay-offset-input").value = overlay.offsetPct;
  document.getElementById("overlay-animation-input").value = overlay.animationMs;
  updateDerivedOcrDisplay(capture.ocrLanguage || deriveOcrLanguage(config.languages.source));
  applyStylePreview(overlay);
}

export function currentOverlayConfigFromForm() {
  return {
    theme: document.getElementById("overlay-theme-input").value,
    position: document.getElementById("overlay-position-input").value,
    fontFamily: document.getElementById("overlay-font-family-input").value,
    fontSize: Number(document.getElementById("overlay-font-size-input").value || 28),
    textColor: document.getElementById("overlay-text-color-input").value,
    bgColor: document.getElementById("overlay-bg-color-input").value,
    radiusPx: Number(document.getElementById("overlay-radius-input").value || 28),
    paddingPx: Number(document.getElementById("overlay-padding-input").value || 20),
    maxWidthVw: Number(document.getElementById("overlay-max-width-input").value || 78),
    blurPx: Number(document.getElementById("overlay-blur-input").value || 20),
    shadowStrength: Number(document.getElementById("overlay-shadow-input").value || 0.45),
    offsetPct: Number(document.getElementById("overlay-offset-input").value || 10),
    animationMs: Number(document.getElementById("overlay-animation-input").value || 220),
  };
}

export function buildConfigPayload() {
  const sourceLanguage = currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput) || "en";
  const targetLanguage = currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput) || "zh";
  const opensubtitles = {
    enabled: dom.opensubtitlesEnabledInput.checked,
    apiKey: dom.opensubtitlesApiKeyInput.value.trim(),
    enableOrgFallback: dom.opensubtitlesOrgFallbackInput.checked,
  };
  return {
    subtitleSources: {
      opensubtitles,
      subdl: {
        enabled: dom.subdlEnabledInput.checked,
      },
      assrt: {
        enabled: dom.assrtEnabledInput.checked,
        token: dom.assrtTokenInput.value.trim(),
      },
    },
    opensubtitles,
    languages: {
      source: sourceLanguage,
      target: targetLanguage,
    },
    capture: {
      ocrLanguage: deriveOcrLanguage(sourceLanguage),
      intervalMs: Number(document.getElementById("capture-interval-input").value || 1500),
      region: parseRegion(document.getElementById("capture-region-input").value),
    },
    translation: {
      endpoint: document.getElementById("translation-endpoint-input").value.trim(),
      model: document.getElementById("translation-model-input").value.trim(),
      timeoutS: state.config?.translation?.timeoutS ?? 30,
      batchSize: state.config?.translation?.batchSize ?? 5,
    },
    matching: {
      fuzzyThreshold: state.config?.matching?.fuzzyThreshold ?? 65,
      windowSize: state.config?.matching?.windowSize ?? 30,
    },
    overlay: {
      port: state.config?.overlay?.port ?? 8765,
      ...currentOverlayConfigFromForm(),
    },
    debug: {
      mode: state.config?.debug?.mode ?? false,
    },
  };
}

// Render owns the read model that maps backend snapshot state into concrete UI.
export function render() {
  if (!state.snapshot || !state.config) {
    return;
  }

  const snapshot = state.snapshot;
  const sourceLanguage =
    snapshot.source_language || currentLanguageValue(dom.sourceLanguageInput, dom.sourceLanguageCustomInput);
  const targetLanguage =
    snapshot.target_language || currentLanguageValue(dom.targetLanguageInput, dom.targetLanguageCustomInput);
  const searchResults = snapshot.search_results || [];
  const searchMatches = snapshot.search_matches || [];
  const selectedFeatureId = currentFeatureId(snapshot);
  const selectedMatch = searchMatches.find((match) => sameSelectionValue(matchSelectionId(match), selectedFeatureId)) || null;
  const filteredResults = searchResults.filter((result) => resultMatchesSelectedMatch(result, selectedFeatureId));
  const sourceResults = filteredResults
    .filter((result) => {
      if (normalizeLanguageCode(result.language) === normalizeLanguageCode(sourceLanguage)) {
        return true;
      }
      return isChineseFamily(sourceLanguage) && isChineseFamily(result.language);
    })
    .sort((left, right) => {
      const leftExact = normalizeLanguageCode(left.language) === normalizeLanguageCode(sourceLanguage) ? 0 : 1;
      const rightExact = normalizeLanguageCode(right.language) === normalizeLanguageCode(sourceLanguage) ? 0 : 1;
      return leftExact - rightExact;
    });
  const targetResults = filteredResults.filter(
    (result) => normalizeLanguageCode(result.language) === normalizeLanguageCode(targetLanguage),
  );
  const progress = snapshot.progress || {};
  const progressRatio = progress.total ? Math.min(progress.current / progress.total, 1) : 0;
  const sourceSelectionMode = currentSourceSelectionMode(snapshot);
  const selectedSource = selectedSourceResultId(snapshot);
  const selectedTarget = selectedTargetResultId(snapshot);
  const targetSelectionMode = currentTargetSelectionMode(snapshot);
  const selectedSourceResult = filteredResults.find((result) => sameSelectionValue(resultSelectionId(result), selectedSource)) || null;
  const selectedTargetResult = filteredResults.find((result) => sameSelectionValue(resultSelectionId(result), selectedTarget)) || null;
  const fallbackSelected = sourceSelectionMode === "ocr_fallback" && !selectedSource;
  const progressIndeterminate = snapshot.status === "searching" || (progress.total === 0 && !!progress.message);
  const targetConfirmed = Boolean(targetSelectionMode);
  const captureRegionReady = hasCaptureRegion();
  const resultsStep = currentVisibleResultsStep(snapshot);
  const canPrepare = Boolean(selectedFeatureId) && (Boolean(selectedSource) || fallbackSelected) && targetConfirmed;
  const shellView = currentShellView(snapshot);
  const sourceCoverageHint = assrtCoverageHint(sourceLanguage);

  renderShellChrome(shellView, snapshot, selectedMatch);
  document.body.dataset.resultsStep = resultsStep;
  dom.appShell?.setAttribute("data-results-step", resultsStep);

  dom.statusChip.textContent = statusLabel(snapshot.status || "idle");
  dom.statusChip.className = `status-chip ${snapshot.status || "idle"}`;
  dom.statusMessage.textContent = sessionMessage(snapshot, selectedSource, selectedTarget);
  dom.progressStage.textContent = sessionHeadline(snapshot, selectedSource, selectedTarget);
  dom.progressMeta.textContent = progressSummary(snapshot, selectedSource);
  dom.progressFill.classList.toggle("is-indeterminate", progressIndeterminate);
  dom.progressFill.style.width = progressIndeterminate ? "42%" : `${progressRatio * 100}%`;
  dom.searchSubmitButton.disabled = !state.bootstrap.ready || snapshot.status === "searching";
  dom.searchSubmitButton.textContent = snapshot.status === "searching" ? "Searching…" : "Find Subtitles";
  dom.titleMatchStrip.classList.toggle("has-results", searchMatches.length > 0);
  renderTitleMatches(searchMatches, selectedFeatureId);
  dom.searchResultSummary.textContent = buildSearchResultSummary(
    selectedMatch,
    sourceResults,
    targetResults,
    sourceSelectionMode,
    sourceLanguage,
  );
  renderResultsFlow(resultsStep, sourceSelectionMode, targetSelectionMode);
  if (resultsStep === "title") {
    dom.resultsViewTitle.textContent = snapshot.title ? `Matches For ${snapshot.title}` : "Choose a matched title";
    dom.resultsViewCopy.textContent = "Choose the right title from the list.";
    dom.resultsProviderPill.textContent = `${searchMatches.length} title matches`;
    dom.searchResultSummary.textContent = "Step 1 of 3. Pick a matched title first.";
  } else if (resultsStep === "source") {
    dom.resultsViewTitle.textContent = selectedMatch?.displayLabel || "Choose source subtitle";
    dom.resultsViewCopy.textContent = sourceCoverageHint
      ? `Select the source subtitle you want to sync against. ${sourceCoverageHint}`
      : "Select the source subtitle you want to sync against.";
    dom.resultsProviderPill.textContent = `${sourceResults.length} source choices`;
    dom.searchResultSummary.textContent = sourceCoverageHint
      ? `Step 2 of 3. If nothing fits, you can still use OCR fallback. ${sourceCoverageHint}`
      : "Step 2 of 3. If nothing fits, you can still use OCR fallback.";
  } else {
    dom.resultsViewTitle.textContent = selectedMatch?.displayLabel || "Choose target subtitle";
    dom.resultsViewCopy.textContent = "Choose a target subtitle or confirm local translation.";
    dom.resultsProviderPill.textContent = `${Math.max(targetResults.length, 1)} target choices`;
    dom.searchResultSummary.textContent = "Step 3 of 3. You can still go back and change the source side.";
  }
  if (dom.resultsStepPill) {
    dom.resultsStepPill.textContent =
      resultsStep === "title" ? "Step 1 · Match title" : resultsStep === "source" ? "Step 2 · Choose source" : "Step 3 · Choose target";
  }
  if (dom.resultsBackButton) {
    dom.resultsBackButton.classList.toggle("hidden", resultsStep === "title");
    dom.resultsBackButton.textContent = resultsStep === "target" ? "Back to source" : "Back to titles";
  }
  if (dom.resultsPrepareButton) {
    dom.resultsPrepareButton.classList.toggle("hidden", resultsStep !== "target");
  }
  renderResultsSelectionSummary({
    snapshot,
    resultsStep,
    selectedMatch,
    selectedSourceResult,
    selectedTargetResult,
    searchMatches,
    filteredResults,
    sourceResults,
    sourceSelectionMode,
    targetSelectionMode,
    sourceLanguage,
    targetLanguage,
  });
  dom.sourceResultCount.textContent = `${sourceResults.length} results`;
  dom.targetResultCount.textContent = `${targetResults.length} results`;
  renderSourceResults(dom.sourceResults, sourceResults, selectedSource, sourceLanguage, {
    selectedMatch,
    sourceSelectionMode,
  });
  renderTargetResults(dom.targetResults, targetResults, selectedTarget, sourceSelectionMode, targetSelectionMode);
  renderSessionSummary(snapshot.prepared_session);
  dom.currentSubtitle.textContent = snapshot.last_subtitle || "No subtitle broadcast yet.";
  dom.prepareButton.disabled = !state.bootstrap.ready || !canPrepare;
  dom.startButton.disabled = !state.bootstrap.ready || !captureRegionReady || !(snapshot.prepared_session && snapshot.status !== "running");
  dom.stopButton.disabled = !state.bootstrap.ready || (snapshot.status !== "running" && snapshot.status !== "stopping");
  dom.prepareButton.textContent = snapshot.prepared_session ? "Prepare Again" : fallbackSelected ? "Prepare OCR Fallback" : "Prepare Session";
  if (dom.resultsPrepareButton) {
    dom.resultsPrepareButton.disabled = dom.prepareButton.disabled;
    dom.resultsPrepareButton.textContent = dom.prepareButton.textContent;
  }
  if (dom.sessionSelectRegionButton) {
    dom.sessionSelectRegionButton.classList.toggle("hidden", !TAURI && captureRegionReady);
    dom.sessionSelectRegionButton.textContent = captureRegionReady ? "Update Capture Area" : "Select Capture Area";
  }
  dom.overlayLink.href = snapshot.overlay_url || apiUrl("/overlay");
}
