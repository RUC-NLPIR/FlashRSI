# FlashRSI cover

The cover uses the original React Bits [ElectricLogo](https://github.com/DavidHDev/react-bits/blob/0cb75b89f16abcbcce340168b06058cac22a1715/src/content/Animations/ElectricLogo/ElectricLogo.jsx) component. Its compact 1600 × 360 canvas pairs a blue-white lightning logo on the left with a large white FlashRSI wordmark. The background keeps the original deep black (#080B10). Moving electric arcs trace the lightning, while blue electric light runs along the wordmark's contours.

Two instances of the same component render the effects. The first uses the built-in lightning shape with stronger arcs and glow; the second traces the vector wordmark through a custom image source. The white letterforms remain readable beneath their blue edge light. Pointer interaction is disabled for capture. [app.jsx](../../scripts/readme-cover/app.jsx) holds the exact configuration. The component source is unchanged, and its license is kept with the renderer.

The [GIF](cover.gif) uses a fresh capture of both components. Each `onRender` callback copies its WebGL output immediately, and the capture composes both effects over the static artwork at twice the final resolution. The encoder downsamples 64 frames, samples all of them for a shared color palette, and reserves the exact background and white letter colors. Small glow fluctuations reuse the previous encoded pixel when all RGB channel differences are at most 8; bright electric strokes still update immediately. Forward and reverse playback produces a 126-frame, 7.56-second loop without changing the shader. [cover.png](cover.png) is one composed still. See the [rendering instructions](../../scripts/readme-cover/README.md) to regenerate the assets.

The FlashRSI wordmark uses Space Grotesk Bold with close spacing. Its outlined glyphs are part of the renderer's [static base](../../scripts/readme-cover/base.svg). The bundled font and its SIL Open Font License are in [assets/fonts](../fonts/).

The demo keeps its three open reels and four illustrative curves before Quick start. Its renderer is [render_readme_hero.py](../../scripts/render_readme_hero.py).
