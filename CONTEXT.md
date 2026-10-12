# Inkage

Generates ready-to-display images for e-paper panels on a schedule, running only on GitHub Actions and publishing static files that devices download.

## Language

**Source**:
One kind of content (calendar, a stock index, weather) that knows how to fetch its data, lay it out, and how often it should refresh.
_Avoid_: Task, type, plugin, screen, mode

**Panel**:
A target display specification: resolution, orientation, and palette (nominal ink colors plus optional measured colors used as the dither target).
_Avoid_: Device, display, profile

**Frame**:
The image a Source produces for one Panel. The canonical artifact is an indexed-palette PNG whose indices follow the Ink Order.
_Avoid_: Image, output, screenshot

**Ink Order**:
The fixed canonical ordering of inks `black, white, red, yellow, blue, green`. A Panel's palette is always a prefix of it (BW = 2, BWR = 3, BWRY = 4, Spectra 6 = 6).

**Encoder**:
An optional device-specific packing of a Frame (packed bitplanes, 1-bit BMP, JPEG). Declared per Panel; the indexed PNG is never replaced by one.
_Avoid_: Exporter, format

**Preview**:
An RGB rendering of a Frame for humans (README, debugging). Never consumed by devices.

**Schedule**:
A Source's refresh policy: a minimum interval plus an optional active window (local time range and weekdays). Outside the window the Source refreshes at a longer fallback interval.
_Avoid_: Cron, period, timer

**Run**:
One execution of the workflow. It evaluates every configured Source's Schedule, regenerates only the Frames that are due, carries the rest over unchanged, publishes the whole Site, and hands over to the next Run.

**Chain**:
The unbroken sequence of Runs in which each Run waits until the Site's earliest next-due time and then starts its successor. The platform's own timer only restarts a Chain that broke.
_Avoid_: Loop, daemon, heartbeat

**Watchlist**:
Several symbols shown together on one Frame by a market Source, as opposed to one symbol per Frame.

**Site**:
The published static output (all current Frames plus a manifest) that devices fetch from GitHub Pages.

**Preset**:
A named, built-in Panel definition (e.g. a specific Waveshare module) that a config can reference instead of spelling out width, height, and palette.

**Manifest**:
The Site's index of every current Frame with its URL, content hash, generation time, and next due time. The Run reads the previous Manifest to decide what is due; devices read it to decide when to wake.
_Avoid_: Index, state file

**Sidecar**:
A per-Frame JSON file beside the Frame holding that Frame's Manifest entry alone, for devices that cannot parse the whole Manifest.
