import { appendFileSync, readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { requireCondition, safeFailure } from "./store-submission.mjs";

const REPO = "PeterShanxin/Meowcal-Sub-2";
const MAINTAINERS = new Set(["PeterShanxin", "ianmeowmeow"]);
// v0.4.1 is the last release handled outside this automation.
const FIRST_AUTOMATED_TAG = "v0.4.2";
const TAG = /^v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/;

function tagParts(tag) {
  const parts = TAG.exec(tag ?? "")?.slice(1).map(Number);
  requireCondition(parts?.every(Number.isSafeInteger), "stable_tag_required");
  return parts;
}

export function verifyRelease(event, latest, env) {
  requireCondition(
    env.GITHUB_REPOSITORY === REPO &&
      env.GITHUB_EVENT_NAME === "release" &&
      MAINTAINERS.has(env.GITHUB_ACTOR) &&
      MAINTAINERS.has(env.GITHUB_TRIGGERING_ACTOR) &&
      env.STORE_RELEASE_AUTOMATION_ENABLED === "true" &&
      event.action === "published",
    "release_not_authorized",
  );
  const release = event.release ?? {};
  assertCurrentRelease(release, env);
  requireCondition(
    env.GITHUB_REF === `refs/tags/${release.tag_name}` &&
      /^[a-f0-9]{40}$/.test(env.GITHUB_SHA ?? "") &&
      ["main", env.GITHUB_SHA].includes(release.target_commitish) &&
      latest.id === release.id &&
      latest.tag_name === release.tag_name &&
      latest.draft === false &&
      latest.prerelease === false &&
      latest.published_at === release.published_at,
    "release_identity_mismatch",
  );
  return release.tag_name.slice(1);
}

function assertCurrentRelease(release, env) {
  const candidate = tagParts(release.tag_name);
  for (const tag of [FIRST_AUTOMATED_TAG, env.STORE_FIRST_RELEASE_TAG]) {
    const first = tagParts(tag);
    const component = candidate.findIndex((number, i) => number !== first[i]);
    requireCondition(
      component < 0 || candidate[component] > first[component],
      "release_before_activation",
    );
  }
  requireCondition(
    release.draft === false &&
      release.prerelease === false &&
      Number.isSafeInteger(release.id) &&
      release.id > 0 &&
      release.html_url === `https://github.com/${REPO}/releases/tag/${release.tag_name}`,
    "release_identity_mismatch",
  );
  const activation = Date.parse(env.STORE_RELEASE_NOT_BEFORE ?? "");
  const published = Date.parse(release.published_at ?? "");
  requireCondition(
    Number.isFinite(activation) && Number.isFinite(published) && published >= activation,
    "release_before_activation",
  );
}

export function verifyBuildRun(event, run, workflow, latest, env) {
  requireCondition(
    env.GITHUB_REPOSITORY === REPO &&
      env.GITHUB_EVENT_NAME === "workflow_run" &&
      env.GITHUB_REF === "refs/heads/main" &&
      env.STORE_RELEASE_AUTOMATION_ENABLED === "true" &&
      event.action === "completed" &&
      Number.isSafeInteger(run.id) &&
      run.id > 0 &&
      event.workflow_run?.id === run.id &&
      Number.isSafeInteger(run.run_attempt) &&
      run.run_attempt > 0 &&
      event.workflow_run.run_attempt === run.run_attempt &&
      run.workflow_id === workflow.id &&
      workflow.path === ".github/workflows/microsoft-store.yml" &&
      run.repository?.full_name === REPO &&
      run.head_repository?.full_name === REPO &&
      run.event === "release" &&
      run.status === "completed" &&
      run.conclusion === "success" &&
      MAINTAINERS.has(run.actor?.login) &&
      MAINTAINERS.has(run.triggering_actor?.login) &&
      /^[a-f0-9]{40}$/.test(run.head_sha ?? ""),
    "release_build_not_authorized",
  );
  assertCurrentRelease(latest, env);
  requireCondition(
    ["main", run.head_sha].includes(latest.target_commitish),
    "release_build_source_mismatch",
  );
  return {
    run_id: run.id,
    artifact: `store-submission-${run.run_attempt}`,
    tag: latest.tag_name,
    commit: run.head_sha,
    release_id: latest.id,
  };
}

async function github(path) {
  const response = await fetch(`https://api.github.com/repos/${REPO}${path}`, {
    headers: { Authorization: `Bearer ${process.env.GITHUB_TOKEN}`, Accept: "application/vnd.github+json" },
    redirect: "error",
    signal: AbortSignal.timeout(30000),
  });
  requireCondition(response.ok, "github_latest_unavailable");
  return response.json();
}

async function main() {
  const event = JSON.parse(readFileSync(process.env.GITHUB_EVENT_PATH, "utf8"));
  const latest = await github("/releases/latest");
  if (process.env.GITHUB_EVENT_NAME === "release") {
    console.log(verifyRelease(event, latest, process.env));
    return;
  }
  const runId = event.workflow_run?.id;
  requireCondition(Number.isSafeInteger(runId) && runId > 0, "release_build_not_authorized");
  const [run, workflow] = await Promise.all([
    github(`/actions/runs/${runId}`),
    github("/actions/workflows/microsoft-store.yml"),
  ]);
  const result = verifyBuildRun(event, run, workflow, latest, process.env);
  for (const [key, value] of Object.entries(result)) {
    appendFileSync(process.env.GITHUB_OUTPUT, `${key}=${value}\n`);
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  try {
    await main();
  } catch (error) {
    console.error(safeFailure(error));
    process.exitCode = 1;
  }
}
