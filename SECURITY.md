# Security policy

## Reporting a vulnerability

Report privately through
[GitHub private vulnerability reporting](https://github.com/PeterShanxin/Meowcal-Sub-2/security/advisories/new).
If the form is unavailable, email the maintainer at **shanxin@u.nus.edu**.
Do not open a public issue for an undisclosed vulnerability.

Include the affected version, Windows architecture, reproduction steps, and
the impact you observed. Use synthetic text and images. Do not include source
credentials, the studio access token, captured dialogue, viewing screenshots,
or unredacted logs. There is no bug bounty or guaranteed response time.

## Sensitive data and boundaries

- Screen captures, OCR results, translations, and downloaded subtitle files
  may contain private or copyrighted material.
- Provider credentials are stored in plaintext TOML in the user's application
  profile. The per-run studio token is also stored there. Normal logs use INFO;
  explicit verbose mode adds OCR/subtitle traces. Titles, errors, and sensitive
  details can remain in normal logs.
- Runtime and model download URLs, hashes, release credentials, and build
  workflows are part of the supply chain.

The studio binds to loopback and checks a per-run token and request origin.
These controls restrict unauthenticated requests and foreign web pages; they
do not isolate the app from software running with access to the same Windows
user profile. Do not expose the studio port through a proxy or port forward.

Translation inference runs locally. Subtitle searches, downloads, optional
TMDb metadata, Google Fonts, and model/runtime installation use network services.

## Supported versions

Security fixes target the latest
[release](https://github.com/PeterShanxin/Meowcal-Sub-2/releases) and `main`.
Older packaged versions are not separately maintained.
