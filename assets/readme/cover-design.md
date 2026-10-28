# FlashRSI cover

The cover runs the original React Bits [ElectricLogo](https://github.com/DavidHDev/react-bits/blob/0cb75b89f16abcbcce340168b06058cac22a1715/src/content/Animations/ElectricLogo/ElectricLogo.jsx) component. A blue-white lightning outline with moving arcs sits beside the static white wordmark. The plain dark background and open space preserve the minimal layout.

The component uses its built-in lightning shape. Its main settings are three strands, scale 0.52, blue glow, reduced bend and crackle, and disabled pointer interaction. [app.jsx](../../scripts/readme-cover/app.jsx) holds the exact configuration. The component source is unchanged, and its license is kept with the renderer.

The [GIF](cover.gif) contains actual WebGL frames captured through `onRender`; [cover.png](cover.png) is one captured still. Forward and reverse playback closes the loop without changing the shader. See the [capture instructions](../../scripts/readme-cover/README.md) to regenerate the assets.

The FlashRSI wordmark uses Space Grotesk Bold with close spacing. Its outlined glyphs are part of the renderer's [static base](../../scripts/readme-cover/base.svg). The bundled font and its SIL Open Font License are in [assets/fonts](../fonts/).

The demo keeps its three open reels and four illustrative curves before Quick start. Its renderer is [render_readme_hero.py](../../scripts/render_readme_hero.py).
