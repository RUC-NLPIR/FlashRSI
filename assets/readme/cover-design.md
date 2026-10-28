# FlashRSI cover

The cover uses the original React Bits [ElectricLogo](https://github.com/DavidHDev/react-bits/blob/0cb75b89f16abcbcce340168b06058cac22a1715/src/content/Animations/ElectricLogo/ElectricLogo.jsx) component. Its compact 1600 × 360 canvas pairs a blue-white lightning logo on the left with a large white FlashRSI wordmark. The background keeps the original deep black (#080B10). Moving electric arcs trace the lightning; the wordmark stays still.

The component uses its built-in lightning shape. Its main settings are three strands, scale 0.72, blue glow, reduced bend and crackle, and disabled pointer interaction. [app.jsx](../../scripts/readme-cover/app.jsx) holds the exact configuration. The component source is unchanged, and its license is kept with the renderer.

The [GIF](cover.gif) reuses the actual WebGL frames captured for the previous cover through `onRender`. The encoder repositions and scales the lightning beside the new vector wordmark; this layout update requires no new browser recording. [cover.png](cover.png) is one composed still. Forward and reverse playback closes the loop without changing the shader. See the [rendering instructions](../../scripts/readme-cover/README.md) to regenerate the assets.

The FlashRSI wordmark uses Space Grotesk Bold with close spacing. Its outlined glyphs are part of the renderer's [static base](../../scripts/readme-cover/base.svg). The bundled font and its SIL Open Font License are in [assets/fonts](../fonts/).

The demo keeps its three open reels and four illustrative curves before Quick start. Its renderer is [render_readme_hero.py](../../scripts/render_readme_hero.py).
