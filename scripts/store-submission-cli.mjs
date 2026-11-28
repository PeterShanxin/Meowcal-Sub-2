import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import {
  createStoreClient,
  reportSubmissionInventory,
  requireCondition,
  safeFailure,
  submitRelease,
} from "./store-submission.mjs";

try {
  const [mode, version, upload, extra] = process.argv.slice(2);
  requireCondition(!extra, "arguments_invalid");
  if (mode === "inventory" && !version && !upload) {
    console.log(JSON.stringify(await reportSubmissionInventory(createStoreClient(process.env))));
  } else {
    requireCondition(mode === "submit" && version && upload, "arguments_invalid");
    const bytes = await readFile(upload);
    requireCondition(bytes.length > 1000 && bytes.length < 300_000_000, "submission_bundle_invalid");
    const md5 = createHash("md5").update(bytes).digest("base64");
    const client = createStoreClient(process.env);
    console.log(JSON.stringify(await submitRelease(client, { storeVersion: version }, { bytes, md5 },
      (submissionId) => console.log(JSON.stringify({ submissionId, status: "created_uncommitted" })),
    )));
  }
} catch (error) {
  console.error(safeFailure(error));
  process.exitCode = 1;
}
