RRSI + MiniAgent + Terminal-Bench 2.0, seed42, T2 k2 m2. Final selected test: 23/30 = 76.6666666667%.

full-run.tar.gz preserves original experiment paths, candidate Snapshots, trajectories, Target/Worker native records, known and unknown usage, selection and recovery history. Exact duplicates are tar hardlinks. manifest.json lists every included path, SHA256, mode and mtime; verification.json confirms archive SHA256 and local per-file verification.

The full initial and selected Snapshot JSONs are exported beside the archive for further OOD use. Original final result and completion verification are also exported unchanged.

Previously archived Claude Code, SWE and other OOD runs, installed environments, Docker images, registry caches, and routine copied audit exports are excluded. The exact scope is in manifest.json. Remote originals and the remote verified archive were not deleted.

Credential handling: 11 original request/log copies contained provider credentials. Only the archived copies were redacted; remote originals were not modified. For these files manifest.json retains source_sha256/source_bytes alongside the archived sha256/bytes. Per-file archive verification uses the archived hashes.


Publication: the full archive is preserved byte-for-byte. When split, concatenate `full-run.tar.gz.part*` in lexical order. Large JSON manifests are losslessly gzip-compressed. Source verification and historical protocol/scoring exceptions remain unchanged. Historical symlinks may refer to original environment paths: this audit reads link metadata without extracting/following it. Use safe extraction filters and do not restore historical links as root. No new model or grader calls.

Historical incomplete downloads inside failed attempts are retained unchanged and documented in `historical-partial-downloads.json`; their nested tar data is incomplete. This does not indicate corruption of the enclosing verified full-run archive.
