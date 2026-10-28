# ElectricLogo cover renderer

This preview runs the original React Bits [ElectricLogo](https://github.com/DavidHDev/react-bits/blob/0cb75b89f16abcbcce340168b06058cac22a1715/src/content/Animations/ElectricLogo/ElectricLogo.jsx) component supplied for this design, using React and OGL. The component source is unchanged. Its MIT + Commons Clause license is included in [REACT-BITS-LICENSE.md](REACT-BITS-LICENSE.md).

From this directory:

```bash
npm ci
npm run preview
```

Open the printed local URL in a browser with WebGL 2 support. The 1600 × 360 artwork keeps the deep black background and white Space Grotesk wordmark from [base.svg](base.svg). [app.jsx](app.jsx) runs two ElectricLogo instances: one traces the lightning on the left, and the other adds blue electric light to the wordmark's contours.

After both effects warm up, click **Record 64 frames**. Each component's `onRender` callback immediately copies its WebGL drawing buffer. The capture combines the two effects with the static artwork in a 2D canvas at twice the output resolution and saves a PNG every 60 ms to the local preview server. The page shows the capture directory when all frames have been written.

From the repository root, encode those frames:

```bash
uv run --script scripts/render_readme_cover.py /path/shown/by/the/preview
```

The encoder downsamples with Lanczos filtering and writes `assets/readme/cover.gif` and `cover.png`. A shared palette samples every captured frame, preserving blue arcs that appear only briefly; the deep black background and white wordmark colors are reserved exactly. For smaller GIF delta frames, pixels whose RGB channels all change by at most 8 reuse the previous encoded pixel. Larger changes update immediately, and gradual changes accumulate against the encoded frame. The GIF plays the captured frames forward and backward to close the loop, since the original shader uses evolving noise and random arcs. Its 126 frames play for 7.56 seconds. Both electric effects come from the React component's actual WebGL output.

For older captures from the previous 1600 × 440 layout, the encoder still supports legacy reframing:

```bash
uv run --script scripts/render_readme_cover.py /path/to/original/capture --reframe-original
```

This extracts and scales the original lightning effect and composes it with the static SVG wordmark. It accepts original captures at either 1× or 2× resolution. This mode keeps the wordmark static and cannot produce the new wordmark animation.
