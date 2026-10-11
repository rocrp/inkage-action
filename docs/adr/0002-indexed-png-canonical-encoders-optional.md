# Indexed PNG in canonical Ink Order is the Frame; device formats are optional Encoders

Target devices disagree on wire format: raw 2bpp or 1-bit BMP (InkSight-family firmware), 4bpp PCIM (PhotoPainter), JPEG (OpenEPaperLink), palette PNG (BLE price-tag compiler). We make the Frame a palette-indexed PNG with exactly N entries ordered by the fixed Ink Order (`black, white, red, yellow, blue, green`, panels use a prefix), and treat every device format as an Encoder that is a pure function of that PNG, enabled per Panel. Index meaning is therefore identical across BW/BWR/BWRY/Spectra 6 and across all Encoders, and a host-side bridge can consume the PNG directly.

## Considered options

- **Emit only a device-native binary** (inkboard's 2bpp): simplest for one firmware, useless for others and opaque to humans.
- **RGB PNG and let devices quantize**: pushes dithering onto MCUs with ~30 KB RAM; rejected.
- **Per-device palette orderings**: breaks sharing one dithered Frame between Encoders; rejected.

## Consequences

- Preview is a separate RGB rendering; nothing consumes the indexed PNG visually.
- Pillow's `quantize` must receive a palette image with exactly N entries (padding to 256 creates phantom indices firmware cannot map).
- Adding a device = adding an Encoder, never touching Sources.
