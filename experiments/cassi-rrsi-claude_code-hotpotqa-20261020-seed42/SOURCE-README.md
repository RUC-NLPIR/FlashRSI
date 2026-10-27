# RRSI hotpotqa-claude_code

Downloaded archive: full-run.tar.gz. SHA256 verified against the fully verified remote archive.

Main experiment records, snapshots, trajectories and recovery history are included. OOD experiments, shared installed environments, Docker images and unrelated live runs are excluded. Original remote records and archives are preserved.

See verification.json and manifest.json for exact provenance, scope and hashes. This is not a full machine image.


Publication: the full archive is preserved byte-for-byte. When split, concatenate `full-run.tar.gz.part*` in lexical order. Large JSON manifests are losslessly gzip-compressed. Source verification and historical protocol/scoring exceptions remain unchanged. Historical symlinks may refer to original environment paths: this audit reads link metadata without extracting/following it. Use safe extraction filters and do not restore historical links as root. No new model or grader calls.
