# ElectricLogo cover renderer

This preview runs the original React Bits [ElectricLogo](https://github.com/DavidHDev/react-bits/blob/0cb75b89f16abcbcce340168b06058cac22a1715/src/content/Animations/ElectricLogo/ElectricLogo.jsx) component supplied for this design, using React and OGL. The component source is unchanged. Its MIT + Commons Clause license is included in [REACT-BITS-LICENSE.md](REACT-BITS-LICENSE.md).

From this directory:

```bash
npm ci
npm run preview
```

Open the printed local URL in a browser with WebGL 2 support. The left artwork comes from [base.svg](base.svg); [app.jsx](app.jsx) places the ElectricLogo lightning on the right and sets its colors and animation parameters.

After the effect warms up, click **Record 48 frames**. The `onRender` callback immediately copies the WebGL canvas into a composed 2D canvas at twice the output resolution, then saves each PNG to the local preview server. The page shows the capture directory when all frames have been written.

From the repository root, encode those frames:

```bash
uv run --script scripts/render_readme_cover.py /path/shown/by/the/preview
```

The encoder downsamples with Lanczos filtering and writes `assets/readme/cover.gif` and `cover.png`. The GIF plays the captured frames forward and backward to close the loop, since the original shader uses evolving noise and random arcs. Its 94 frames play for 7.52 seconds. The React component, rather than a procedural approximation, produces every captured frame.
