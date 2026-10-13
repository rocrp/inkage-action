# Bundled fonts

Full upstream fonts, byte-for-byte unmodified; no subsetting, synthetic bold,
or conversion. Redistributed under SIL Open Font License 1.1; license and
component copyright notices retained in `licenses/`. Rendered images retain
their own license. Application MIT license does not replace font licenses.

| CSS family | Native grid | Version | File SHA-256 |
|---|---:|---|---|
| Fusion Pixel 12 | 12 px | 2026.09.25 | `e84b6d1ab8f2e25084761eb61c88b373bf1fa0b0c5e9b559d5b1d90e4d658c86` |
| Fusion Pixel 10 | 10 px | 2026.09.25 | `ec2157244c7ff4890bd1048056ffb8d77318da116a119ad594ef0c2d8197e1ad` |
| Unifont | 16 px | 18.0.01 | `88d0a14d4aa9a96419720b39ba5da921a59560d76d4ec7d523acc06ed85cd3c2` |
| Departure Mono | 11 px | 1.500 | `4d53f663155cf8bf7ffc8e688776e719625f7bbb80a8d90073438b249261a2e0` |

Use integer multiples of native grid. Fusion files use proportional Simplified
Chinese variant. Departure Mono covers Latin/numbers; pair with Fusion for
Chinese. Unifont standard OTF covers BMP; no supplementary-plane promise.

## Provenance

- Fusion: [2026.09.25 release](https://github.com/TakWolf/fusion-pixel-font/releases/tag/2026.09.25),
  `fusion-pixel-12px-proportional-sc.otf`, `fusion-pixel-10px-proportional-sc.otf`.
  Copyright (c) 2022 TakWolf. Original release component license directories
  retained for Galmuri, Ark Pixel, Cubic 11, Boutique Bitmap 9x9 as applicable.
- Unifont: [original OTF](https://unifoundry.com/pub/unifont/unifont-18.0.01/font-builds/unifont-18.0.01.otf).
  Copyright © 1998–2026 Roman Czyborra, Paul Hardy, Qianqian Fang, Andrew Miller,
  Johnnie Weaver, David Corbett, Ælla Chiana Moskopp, Rebecca Bettencourt,
  Ho-Seok Ee, et al. Compiled fonts dual-licensed OFL 1.1 / GPL 2+ with font
  embedding exception; shipped here under OFL. Upstream full licensing notice
  also retained.
- Departure Mono: [original OTF at fixed commit](https://github.com/rektdeckard/departure-mono/blob/75152a3f1e6dacdd248a6c397c97dbf27e33eea0/public/assets/DepartureMono-Regular.otf),
  renamed file to `departure-mono-1.500.otf` without modifying bytes.
  Copyright 2022–2024 Helena Zhang.

All assets reside inside the Python package so installed wheels render without
system font installation or network downloads.
