import assert from "node:assert/strict";
import test from "node:test";
import { verifyBuildRun, verifyRelease } from "../scripts/store-release-gate.mjs";
import { PRODUCT_ID, STORE_IDENTITY, submitRelease, updateSubmission } from "../scripts/store-submission.mjs";

const sha = "a".repeat(40);
const repo = "PeterShanxin/Meowcal-Sub-2";
const release = {
  id: 7,
  tag_name: "v0.4.2",
  target_commitish: "main",
  draft: false,
  prerelease: false,
  published_at: "2026-11-30T01:00:00Z",
  html_url: `https://github.com/${repo}/releases/tag/v0.4.2`,
};
const env = {
  GITHUB_REPOSITORY: repo,
  GITHUB_EVENT_NAME: "release",
  GITHUB_ACTOR: "PeterShanxin",
  GITHUB_TRIGGERING_ACTOR: "PeterShanxin",
  GITHUB_REF: "refs/tags/v0.4.2",
  GITHUB_SHA: sha,
  STORE_FIRST_RELEASE_TAG: "v0.4.2",
  STORE_RELEASE_NOT_BEFORE: "2026-11-30T00:00:00Z",
  STORE_RELEASE_AUTOMATION_ENABLED: "true",
};
const event = { action: "published", release };

test("only the latest trusted stable release after both cutoffs qualifies", () => {
  assert.equal(verifyRelease(event, release, env), "0.4.2");
  for (const change of [
    { GITHUB_REPOSITORY: "fork/repo" },
    { GITHUB_ACTOR: "dependabot[bot]" },
    { GITHUB_TRIGGERING_ACTOR: "other" },
    { GITHUB_REF: "refs/heads/main" },
    { STORE_FIRST_RELEASE_TAG: "v0.4.10" },
    { STORE_RELEASE_NOT_BEFORE: "2026-11-30T02:00:00Z" },
    { STORE_RELEASE_AUTOMATION_ENABLED: "false" },
  ]) {
    assert.throws(() => verifyRelease(event, release, { ...env, ...change }));
  }
  assert.throws(() => verifyRelease(event, { ...release, id: 99 }, env), /identity_mismatch/);
  assert.throws(() => verifyRelease({ ...event, action: "edited" }, release, env), /not_authorized/);
  assert.throws(() =>
    verifyRelease({ ...event, release: { ...release, target_commitish: "untrusted" } }, release, env));
});

test("the default-branch submitter accepts only the authorized release build and attempt", () => {
  const run = {
    id: 42,
    run_attempt: 2,
    workflow_id: 5,
    repository: { full_name: repo },
    head_repository: { full_name: repo },
    head_sha: sha,
    actor: { login: "PeterShanxin" },
    triggering_actor: { login: "PeterShanxin" },
    event: "release",
    status: "completed",
    conclusion: "success",
  };
  const notification = { action: "completed", workflow_run: { id: 42, run_attempt: 2 } };
  const workflow = { id: 5, path: ".github/workflows/microsoft-store.yml" };
  const next = { ...env, GITHUB_REF: "refs/heads/main", GITHUB_EVENT_NAME: "workflow_run" };
  assert.deepEqual(verifyBuildRun(notification, run, workflow, release, next), {
    run_id: 42, artifact: "store-submission-2", tag: "v0.4.2", commit: sha, release_id: 7,
  });
  for (const change of [
    { run_attempt: 3 },
    { workflow_id: 6 },
    { event: "pull_request" },
    { conclusion: "failure" },
    { head_repository: { full_name: "fork/repo" } },
    { triggering_actor: { login: "stranger" } },
  ]) {
    assert.throws(() => verifyBuildRun(notification, { ...run, ...change }, workflow, release, next));
  }
});

const candidate = { storeVersion: "1.0.2.0" };
const listings = { "en-us": { baseListing: { releaseNotes: "Unchanged" } } };
const published = {
  id: "101",
  status: "Published",
  applicationPackages: [{ version: "1.0.1.0", fileName: "old.msix", fileStatus: "Uploaded" }],
  pricing: { priceId: "Free" },
  listings,
};
const app = {
  id: PRODUCT_ID,
  packageIdentityName: STORE_IDENTITY.name,
  publisherName: STORE_IDENTITY.publisher,
  lastPublishedApplicationSubmission: { id: published.id },
};

test("submission changes only the packages and publication mode", () => {
  const draft = { ...published, status: "PendingCommit" };
  const next = updateSubmission(draft, candidate, "Immediate");
  assert.deepEqual(next.listings, listings);
  assert.deepEqual(next.pricing, published.pricing);
  assert.equal(next.targetPublishMode, "Immediate");
  assert.equal(next.applicationPackages[0].fileStatus, "PendingDelete");
  assert.equal(next.applicationPackages[1].fileName, "MeowcalSub2-1.0.2.0.msixbundle");
  assert.equal(draft.applicationPackages[0].fileStatus, "Uploaded");
  assert.throws(() => updateSubmission(draft, { storeVersion: "1.0.1.0" }), /not_increasing/);
});

test("wrong product and an existing draft cannot trigger any write", async () => {
  const readOnly = {
    authenticate: async () => {},
    getSubmission: async () => ({
      id: "202",
      targetPublishMode: "Immediate",
      applicationPackages: [{ fileName: "MeowcalSub2-1.0.2.0.msixbundle", fileStatus: "PendingUpload" }],
    }),
    getStatus: async () => ({ status: "PendingCommit" }),
  };
  await assert.rejects(
    submitRelease({ ...readOnly, getApp: async () => ({ ...app, id: "wrong" }) }, candidate, {}),
    /identity_mismatch/,
  );
  const client = { ...readOnly, getApp: async () => ({ ...app, pendingApplicationSubmission: { id: "202" } }) };
  await assert.rejects(submitRelease(client, candidate, {}), /status_unexpected/);
  assert.deepEqual(
    await submitRelease({ ...client, getStatus: async () => ({ status: "Certification" }) }, candidate, {}),
    { submissionId: "202", status: "Certification", reused: true },
  );
});

test("a lost commit response is reconciled by reading status, not by re-committing", async () => {
  let pending;
  let payload;
  let commits = 0;
  let uploaded = false;
  const draft = { ...published, id: "202", status: "PendingCommit", fileUploadUrl: "unused" };
  const client = {
    authenticate: async () => {},
    getApp: async () => ({ ...app, pendingApplicationSubmission: pending }),
    getSubmission: async (id) => id === published.id ? published : payload,
    create: async () => { pending = { id: "202" }; return draft; },
    update: async (_, body) => { payload = body; },
    upload: async () => { uploaded = true; },
    commit: async () => { assert.equal(uploaded, true); commits++; throw new Error("socket reset"); },
    getStatus: async () => ({ status: "Certification" }),
  };
  assert.deepEqual(await submitRelease(client, candidate, {}), {
    submissionId: "202", status: "Certification", reused: false,
  });
  assert.equal(commits, 1);
});
