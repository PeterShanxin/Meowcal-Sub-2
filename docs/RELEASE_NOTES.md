# Release notes

Write `docs/releases/v<version>.md` and `v<version>.zh-CN.md` before tagging.
Use the English file as the GitHub release body and link the Chinese file at
the release tag. [v0.3.0](releases/v0.3.0.md) is the reference example.

## Layout and voice

1. Title: `# Meowcal Sub 2 v<version>`, then a link to the other language.
2. One bold sentence naming the biggest change and a short sentence explaining
   why it matters.
3. `## ✨ Highlights`: two to five bullets with an icon, a bold benefit and one
   or two explanatory sentences. Link the relevant pull request.
4. `## Fixes and improvements`: short bullets about changes users notice.
5. Known limitations only when a concrete issue affects the update decision.
6. `## 📦 Download`: map Intel/AMD and Snapdragon/ARM PCs to their installers;
   mention portable ZIPs, bundled Core, model downloads and `SHA256SUMS.txt`.
   Put manual-upgrade requirements and the Windows publisher warning here.

Keep the notes readable in a minute. Name controls as they appear in the app.
Explain the user's benefit rather than implementation details. Leave routine
dependency updates, CI results and release preparation out of the notes; record
verification in the release PR. Include measurements only with their sample
and evidence. Keep both languages equivalent in meaning.

## Publication

Follow the [packaging and acceptance process](developer-guide.md#build-a-windows-distribution).
Publish only after checking both architectures and the exact signed installers.
Upload the installers, portable ZIPs, signatures, architecture checksum lists,
combined `SHA256SUMS.txt` and `latest.json`. Check that the manifest points to
the uploaded installers and uses their signatures. Preserve the updater key.

Update release applicability in both user guides and README files. After
publication, update the [product page](developer-guide.md#build-a-windows-distribution).
Sub 2's updater manifest contains version and download information; it does not
currently display release highlights or feed a Microsoft Store submission.
