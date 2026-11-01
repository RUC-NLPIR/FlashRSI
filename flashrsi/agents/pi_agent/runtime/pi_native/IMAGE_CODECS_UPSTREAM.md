# Vendored image codec provenance

`photon_image.py` ports the algorithms used by `@silvia-odwyer/photon-node`
0.3.4's `photon-rs` image 0.24.8 dependency: `imageops::resize` Lanczos3,
`png` 0.17's adaptive filters plus `fdeflate` Fast compression, and image's
JPEG encoder. `vp8_decoder.py` is a source port of image 0.24.8's keyframe VP8
decoder, including prediction, integer transforms and loop filtering. The
upstream image-rs code is MIT/Apache-2.0; notices are retained in
`PARTIAL_JSON_LICENSE` and this repository's `LICENSE` files.

The development fixtures under `tests/fixtures/pi_images_upstream.json` and
`pi_image_decode_upstream.json` are generated from the pinned Photon package
and are not loaded by production code.
