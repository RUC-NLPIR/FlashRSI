AppWorld RRSI MiniAgent, seed42, T5 k2 m2. Final selected test: 142/168 = 84.5238095238%.

full-run.tar.gz contains original selected experiment paths, all included recovery history, native records, full known/unknown usage evidence, all candidate Snapshots, frozen source and support code.
manifest.json lists every entry, SHA256, mode and mtime. Exact duplicates are tar hardlinks. verification.json confirms both archive SHA256 and local per-file SHA256.
The original controller error is preserved: the final native call exhausted its fixed response token budget. The unchanged FrozenAppWorld.grade assigns 0 to that error; no Solver/model was rerun. See completed-original-verification.json.
Installed environments, Docker images, original benchmark installation, unrelated experiments and BFCL OOD are outside this archive. Remote originals were not deleted.


Publication: the full archive is preserved byte-for-byte. When split, concatenate `full-run.tar.gz.part*` in lexical order. Large JSON manifests are losslessly gzip-compressed. Source verification and historical protocol/scoring exceptions remain unchanged. Historical symlinks may refer to original environment paths: this audit reads link metadata without extracting/following it. Use safe extraction filters and do not restore historical links as root. No new model or grader calls.
