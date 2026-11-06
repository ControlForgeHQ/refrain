# refrain
An open-source e-paper display for rotating quotations, progressive reveals, and interactive content.

## Development setup

Refrain's hardware-independent components can be developed and tested on Windows, Linux, and macOS without physical display hardware.

Python 3.13 or newer is required.

Create a virtual environment in the repository root.

### Windows (PowerShell)

```powershell
py -3.13 -m venv .venv
```

Install Refrain and its development dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Run the standard validation checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m black --check src tests
```

### Linux and macOS

Create the virtual environment:

```sh
python3 -m venv .venv
```

Install Refrain and its development dependencies:

```sh
.venv/bin/python -m pip install -e '.[dev]'
```

Run the standard validation checks:

```sh
.venv/bin/python -m pytest -v
.venv/bin/python -m ruff check src tests
.venv/bin/python -m black --check src tests
```

### Validation expectations

All three validation commands must pass before an implementation is considered ready for review.

Run the commands from the repository root.

Use the project's virtual environment so that validation does not depend on globally installed Python packages or development tools.

The commands are intentionally identical across platforms apart from the virtual environment's Python executable path.

Validation results should identify the operating system, Python version, and any tests that could not be performed.

Hardware-independent validation does not replace physical display validation where required.

## Loading application configuration

`load_application_config` reads and validates `config.yaml`, returning resolved paths, effective font, background, and decoration registries, and the settings required by downstream components. Missing optional settings use documented defaults; invalid optional settings and unknown fields are reported through Python logging and do not discard unrelated valid settings. Required values without usable fallbacks remain fatal. Relative content paths are based on the configuration file's directory; relative custom-resource paths use their respective user-asset category directories. See [`examples/config.yaml`](examples/config.yaml) and [`docs/CONTENT_FORMAT.md`](docs/CONTENT_FORMAT.md) for the authoritative resource-path contract.

```python
from refrain import ApplicationConfigurationError, load_application_config

try:
    config = load_application_config("config.yaml")
except ApplicationConfigurationError as error:
    for diagnostic in error.diagnostics:
        print(diagnostic)
else:
    font = config.fonts["lora"]
```

Bundled fonts are package resources, not paths relative to the current directory or source checkout. Use `importlib.resources.as_file(font.path)` when an installed font loader requires a filesystem path; the `FontResource` path can also be opened directly for Pillow.

Custom fonts are discovered from `assets/fonts/` beside the effective configuration file. Put a `font.yaml` manifest and its face files in a directory under that category; for example:

```yaml
format: 1
id: my-serif
faces:
  regular: MySerif.ttf
  italic: MySerif-Italic.ttf
font_faces:
  attribution: italic
```

The face paths are relative to the manifest. Each bundle needs a usable `regular` face; all discovered bundles are available by identifier, but only identifiers listed in `layout.fonts.default` participate in random selection. The optional `font_faces` map expresses preferences within the selected bundle; see the [font-face format and precedence](docs/CONTENT_FORMAT.md#font-face-preferences).

### Daily backgrounds

The five bundled backgrounds have stable, reserved identifiers: `aged-paper`, `canvas`, `cloth`, `ethereal`, and `hex`. They are available through `config.backgrounds` as installed package resources, but are not automatically added to the default pool. Asset provenance is documented in [`src/refrain/assets/README.md`](src/refrain/assets/README.md).

Use `layout.backgrounds.default` to select equally among distinct usable identifiers, including `"none"` for the plain paper-white base. Omission defaults to `["none"]`; invalid or unavailable members are excluded with warnings, duplicates are ignored, and a configured pool with no usable members falls back to `["none"]` with a warning.

```yaml
layout:
  backgrounds:
    default: ["none", "aged-paper", "canvas"]
```

Background assets are discovered recursively under `assets/backgrounds/` beside the effective configuration file. A standalone PNG uses its filename stem as its identifier. A package directory can instead contain a `background.yaml` manifest and its image:

```yaml
format: 1
id: handmade-paper
image: HandmadePaper.png
```

Images must be readable single-frame PNGs in RGB or RGBA mode. Any positive source dimensions and aspect ratio are accepted; backgrounds are uniformly scaled to cover the output, centred, and cropped as needed. RGBA transparency exposes the paper-white base.

A content entry's available `background: "<id>"` wins over the default pool; `background: "none"` suppresses automatic selection. An unavailable, syntactically valid preference warns and falls back to the pool without rejecting the entry. The resolved identifier remains committed across reveals and restarts. If regeneration cannot load that resource, preparation warns and uses paper-white without selecting a replacement or changing committed state. Valid prepared images remain reusable after resource changes. See [Background registry](docs/CONTENT_FORMAT.md#background-registry) and [Background and decoration recovery](docs/ARCHITECTURE.md#background-and-decoration-recovery).

### Daily decorations

The five bundled RGBA overlays are registered under the reserved identifiers `ethereal`, `hex`, `lower-flourish`, `simple-border`, and `top-bottom-borders`. The reserved value `"none"` means no overlay and cannot be registered. Decorations are not automatically added to the default pool; the development example opts into all five and `"none"`.

Configure a default pool and, optionally, custom RGBA PNGs:

```yaml
layout:
  decorations:
    default: ["none", "lower-flourish", "simple-border"]
```

Put custom decoration packages recursively under `assets/decorations/`, with a `decoration.yaml` manifest alongside the artwork:

```yaml
format: 1
id: botanical-corners
image: BotanicalCorners.png
presentation_region: {x: 0.16, y: 0.18, width: 0.68, height: 0.58}
font: lora
background: aged-paper
```

Images must be readable, single-frame RGBA PNGs. Any positive source dimensions and aspect ratio are accepted; decorations are uniformly scaled to fit, centred, and never cropped. The optional presentation region remains normalized to the output canvas. Unavailable font or background preferences are warned about and ignored. Invalid assets are excluded independently. Omitted pools default to `["none"]`; discovered resources are not added automatically.

Fonts, backgrounds, and decorations no longer accept `layout.*.available` registrations. Move custom assets into their category directory and add the required manifest where applicable; update `layout.*.default` only when an asset should participate in automatic selection. Legacy mappings are ignored with migration warnings. Asset identifiers are case-sensitive ASCII letters, digits, hyphens, and underscores, beginning with a letter or digit. User assets cannot shadow bundled assets, and duplicate custom identifiers are all excluded.

A content entry may select a decoration for every quotation it contains:

```yaml
id: evening-reading
decoration: "lower-flourish"
font: "lora"
background: "none"
quotations:
  - "A quotation."
```

An available explicit decoration (including `"none"`) takes precedence over the pool. Otherwise, Refrain selects a decoration first, then resolves the font and background using entry preference, decoration preference, and default pool precedence. The chosen decoration's region override, or the global region when none is supplied, is committed with the presentation. Daily images layer paper-white, background, decoration, then literary text; missing decorations during regeneration are omitted without reselection or changing committed geometry. Valid prepared images remain reusable after resources change. See [Decoration registry](docs/CONTENT_FORMAT.md#decoration-registry) and [Background and decoration recovery](docs/ARCHITECTURE.md#background-and-decoration-recovery).

## Running Refrain

Install the Refrain wheel in the Python environment that will run it, then initialize the per-user installation once:

```sh
.venv/bin/python -m pip install /path/to/refrain.whl
.venv/bin/python -m refrain --initialize
.venv/bin/python -m refrain
```

Initialization copies the packaged `config.default.yaml` to `config.yaml` only when the file is absent, and installs the packaged sample quotation library only when the standard content directory is missing or empty. Existing configuration is preserved byte-for-byte. Existing nonempty content, including directories with hidden or non-YAML entries, is preserved without installing samples or validating the library. The installed configuration is editable and remains authoritative; application upgrades do not replace it or synchronize sample content. `examples/config.yaml` remains a development-oriented example and is not used by application startup.

Initialization is noninteractive and repeatable. It reuses existing real configuration, content, state, and cache directories without modifying existing files. Unexpected files or filesystem links that prevent safe access are reported before installation writes begin. New files are created exclusively, and a failure after creation begins leaves and reports partial results for a later safe retry. Initialization does not create state or history files and does not start display backends or select content.

The standard configuration directory contains `config.yaml`, `content/`, and `assets/` with `fonts/`, `backgrounds/`, and `decorations/` subdirectories. Initialization creates missing asset directories, accepts and preserves existing nonempty directories and files, and does not copy bundled visual resources into them. Refrain discovers valid assets when it loads configuration; it does not modify user-owned assets or add discovered resources to default pools.

### Standard per-user locations

Refrain resolves omitted paths independently of the current working directory:

| Purpose | Linux | Windows |
|---|---|---|
| Configuration and content | `~/.config/refrain/` | `%APPDATA%\Refrain\` |
| User-provided visual assets | `~/.config/refrain/assets/` | `%APPDATA%\Refrain\assets\` |
| Operational state and global history | `~/.local/state/refrain/` | `%LOCALAPPDATA%\Refrain\State\` |
| Prepared artifacts | `~/.cache/refrain/artifacts/` | `%LOCALAPPDATA%\Refrain\Cache\artifacts\` |

On Linux, absolute `XDG_CONFIG_HOME`, `XDG_STATE_HOME`, and `XDG_CACHE_HOME` values replace the corresponding bases, with `refrain` appended. An unset, empty, or relative XDG value uses its per-user fallback under `~`. On macOS, Refrain uses the user's `Library/Application Support` and `Library/Caches` locations.

No system-wide paths are selected automatically when running as root. System deployments should configure explicit paths and service permissions.

Normal operation does not generate a missing configuration or install sample content. If the selected configuration file is absent, Refrain reports its expected path and suggests `python -m refrain --initialize`. It never falls back to the packaged configuration. With `--config /custom/location/config.yaml`, the assets root is `/custom/location/assets/`; Refrain does not also search platform-standard asset locations or the current working directory. Relative content paths remain relative to the selected configuration file, while custom font, background, and decoration paths use their corresponding category directories under that assets root.

If `content.directory` is omitted, the content library defaults to `content/` alongside the selected configuration file. An explicit relative path uses that same configuration-relative base; an absolute path remains absolute.

Existing `layout.*.available` resource mappings are no longer supported and are not migrated. Move custom assets into the category directories and provide manifests for font bundles and packaged backgrounds/decorations. Standalone backgrounds need no manifest.

### Reset and purge

Perform reset and purge only while Refrain is stopped. Both operations manage standard per-user locations only and reject `--config`, `--state`, `--artifacts`, and `--history` overrides. They do not load configuration or start selection, preparation, display backends, or normal application startup.

Reset removes runtime-generated state, the active and rotated global-history files, and generated cache contents. It preserves configuration, the standard content library, the complete user-assets tree, and the standard directory structure. The next normal startup selects and commits a quotation as an initial selection and regenerates required artifacts.

```sh
.venv/bin/python -m refrain --reset
```

The command displays the affected paths and requires an interactive terminal. Type exactly `RESET` to proceed. Any other input, EOF, or unavailable terminal cancels the operation without filesystem changes.

Purge permanently removes the complete Refrain installation from standard per-user configuration, operational, and cache locations, including configuration, content, and custom fonts, backgrounds, and decorations stored in the standard assets directory. It leaves shared parent directories intact, does not follow configuration references to external content or resources, and does not delete resources referenced by absolute external paths.

```sh
.venv/bin/python -m refrain --purge
```

The command displays all standard Refrain-owned locations and requires an interactive terminal. Type exactly `PURGE REFRAIN` to proceed. Any other input, EOF, or unavailable terminal cancels the operation without filesystem changes. After a successful purge, normal startup reports the missing configuration and suggests `--initialize`.

### Continuous and one-shot operation

`python -m refrain` runs continuously, showing the startup information view for 60 seconds by default before presenting the current daily quotation. Set `information_view.duration` to `0` to disable it, or to an integer from `1` through `300` to choose another duration. The interval starts after the first display backend successfully publishes the view. The installed default uses a loopback-only image server at `http://127.0.0.1:8080/display/current`; configure `window` or `waveshare-13in3-e` in `config.yaml` to use a desktop or attached display.

`python -m refrain --once` uses the same standard paths and performs one startup/presentation cycle without scheduling future updates.

The optional path arguments override their respective standard locations:

- `--config` selects a configuration file.
- `--state` selects the persistent selection-state file.
- `--artifacts` selects the derived prepared-image directory.
- `--history` selects the JSONL selection-history file. When omitted, history is `global-history.jsonl` beside the effective state file.
- `--history-segment-size` and `--history-max-segments` configure bounded retention (defaults: 1 MiB per segment and 20 segments, including the active segment).

State and history files are created only by normal runtime operations. State is authoritative for the committed presentation and recovery; global history is a separate historical log. Prepared artifacts are derived and can be regenerated from committed state.

With no committed state, the command selects a quotation for the current display date, commits the complete daily snapshot and repetition history, records the selection independently in global history, prepares the reveal images, and presents the stage required at the current time. All schedule times use host-local civil time and operating-system timezone rules; ambiguous times use their first occurrence and skipped times become due at the first valid instant after the gap. History recording is best-effort and does not block presentation. With existing state, it recovers the committed selection without needing its original content library and reuses valid prepared images (regenerating missing or invalid ones). Missed reveals advance directly to the latest required stage; backward clock adjustments never hide information already revealed.

Operational state uses format version 5 and contains the current snapshot, revision, repetition history, scheduling context, and reveal progress. The scheduling context contains only the display date and day-start time; scheduling uses the host operating system's local timezone rules. The snapshot preserves `font_identifier`, the effective `presentation_metadata.font_faces` identifiers, `background_identifier`, `decoration_identifier`, and the effective presentation region. A version-5 snapshot without face metadata remains recoverable and uses regular for each role; its valid prepared artifacts remain reusable. Global selection history is a separate append-only JSONL log with size-based rotation and bounded retention; it is not read during startup or recovery and never determines the next revision. Development state formats 1 through 4 are unsupported and are not migrated or replaced automatically. Archive or remove an old development state file before starting Refrain; the actionable compatibility error leaves it unchanged.

The continuous runtime gives each configured backend its own worker, so a slow destination cannot block another backend or the scheduling loop. Updates remain synchronous within each worker, are never overlapped for one backend, and coalesce to the latest required image. Recoverable content, storage, and preparation failures retry with monotonic delays increasing from 1 to at most 60 seconds; recoverable display failures retry independently on that backend. A failed presentation never causes reselection, and the globally reached reveal stage is persisted independently of backend success. Invalid application configuration, corrupted authoritative state, or loss of every display destination terminates with status 1 rather than retrying indefinitely. Configuration is loaded once; content is reloaded only when a new selection is needed. After recovering the active image set, the coordinator removes obsolete revision artifacts while retaining the active revision and images used by outstanding backend updates.

Press Ctrl+C or send SIGTERM to stop. Shutdown interrupts scheduling and backend retry waits and waits up to 60 seconds total for workers to finish active updates. It does not interrupt an active update or close its backend concurrently; if an update remains blocked, the application logs the timeout and returns while the daemon worker retains its image and attempts cleanup if the operation later returns. Other backends are still closed without intentionally clearing retained e-paper content. Physical panel behavior still requires hardware validation.

If a backend reports that its instance cannot safely recover (such as a closed desktop window or disabled Waveshare transport), the application releases and disables only that destination. Other configured destinations continue; if all become unavailable, the application exits with status 1. The committed selection remains available for restart.

### Accelerated presentation demo

To cycle through real quotation presentations without changing the system clock or production state:

```powershell
python -m refrain --demo 5
```

`--demo SECONDS` accepts positive finite integers or fractions (for example, `0.5`). It cannot be combined with `--once`. Demo mode uses the configured display backends and suppresses the startup information view regardless of its configured duration.

Each quotation is selected and committed using normal eligibility, priority, repetition, font, and background rules. Its complete canonical image set is prepared or recovered, then presented from the initial stage immediately when ready. Simultaneously scheduled reveals share a stage, absent fields add no stages, and visibility remains cumulative. Each stage's minimum viewing interval begins at the first successful backend acknowledgement; preparation, initialization, and failed updates do not consume it. After the final interval, another quotation is selected. Slow backends may coalesce updates and do not hold up healthy destinations; physical refresh behavior remains backend-owned.

The eligibility date is calculated once using host-local time and the configured day start and stays fixed throughout the session, even across clock changes or display-day boundaries. Demo mode bypasses normal wall-clock scheduling, not selection policy.

State, artifacts, and global history use fresh temporary session storage. `--state`, `--artifacts`, and `--history` are unnecessary and, if supplied, are ignored: their locations are neither read nor written. Repetition history and selection revisions remain effective within the session, but no demo state is resumed by a later invocation. Ctrl+C and SIGTERM stop progression, shut down workers, and remove temporary files. Recoverable failures retry without skipping stages or reselecting committed quotations; loss of every display destination exits with status 1.

### One-shot startup and diagnostics

Add `--once` to run only the startup-and-presentation workflow:

```sh
.venv/bin/python -m refrain --once
```

One-shot execution does not schedule future updates or retry failures. When enabled, it presents the startup information view for its configured duration before the current daily image. For `window` and `image-server`, it holds the daily presentation open until Ctrl+C; the Waveshare panel retains its image after the command exits. The Python API also preserves `run_startup(...)` for one-shot use and exposes `run_application(..., shutdown_event=event)` for continuous operation with an explicit `threading.Event`.

### Targeted content-entry presentation

Use `--show-entry` to render and publish one content entry for inspection:

```sh
.venv/bin/python -m refrain --show-entry shakespeare-hamlet
```

The argument must exactly match a content-entry `id`; matching is case-sensitive and does not use a filename or quotation text. Refrain selects the first quotation in that entry, regardless of its date eligibility, priority, or repetition history. It renders the final canonical reveal stage, so quotation text, source, and attribution are all visible without waiting for reveal times. Fonts, backgrounds, decorations, and presentation regions use the normal resource-resolution rules, including random selection from configured default pools where applicable.

The diagnostic image is saved as `refrain-<entry_id>.png` in the current working directory, not beside the configuration file. Refrain creates the PNG without overwriting an existing file and reports its absolute path on success. The exact saved image is sent once to every configured display backend; Refrain waits for each publication attempt, reports each result, closes the backends, and exits. A failed backend produces a nonzero exit status but does not remove the PNG. The mode cannot be combined with `--once`, `--demo`, `--initialize`, `--reset`, or `--purge`.

The command does not read or modify operational state, global history, or prepared-image artifacts, so it does not consume a quotation or change the current daily presentation. `--state`, `--artifacts`, and `--history` are ignored, even when supplied; `--config` can select an alternate configuration. The reserved target `information` renders Refrain's existing application-owned information screen without loading the content library, consulting the configured information-view duration, or transitioning to a daily quotation. A content entry named `information` remains valid but cannot replace this diagnostic target.

The command exits after publication attempts and backend cleanup. Physical e-paper displays normally retain their image, but `window` and `image-server` are process-scoped: their presentation is no longer accessible after Refrain exits. No serving-backend hold mode is provided by `--show-entry`.

To preview the information view without starting display backends or the application lifecycle:

```powershell
python examples/information_view.py `
    --config examples/config.yaml `
    --output information-view.png
```

### Recovery limitation

Boundary observations exist only during the current process lifetime. After an interruption spanning a display-day transition, the stored scheduling context and an isolated startup timestamp cannot reliably distinguish a missed transition from a clock correction. Recovery therefore conservatively retains the committed selection, presenting its latest required reveal stage, until a subsequent boundary is actually observed. During continuous execution, a forward jump across several display days selects only for the currently appropriate date; a backward correction preserves the current selection until a newly observed boundary. See [boundary recognition](docs/ARCHITECTURE.md#boundary-recognition).

## Display backend selection

Every application configuration must explicitly set a nonempty `display.backends` sequence. Each built-in type may appear at most once; declaration order does not establish priority. Use `window` for development on a graphical Windows or Linux desktop, `waveshare-13in3-e` on a supported Raspberry Pi with the physical panel connected, and/or `image-server` to serve the current complete image to HTTP clients. For the physical panel and HTTP serving together:

```yaml
display:
  backends:
    - type: "waveshare-13in3-e"
    - type: "image-server"
      host: "127.0.0.1"
      port: 8080
```

See [Display backends](docs/CONTENT_FORMAT.md#display-backends) for the configuration contract.

The image server defaults to loopback-only access at `http://127.0.0.1:8080/display/current`. Configure it explicitly to accept connections from other devices on a trusted local network:

```yaml
display:
  backends:
    - type: "image-server"
      host: "0.0.0.0"
      port: 8080
```

With `0.0.0.0`, open `http://<refrain-host-lan-ip>:8080/display/current` from another device and allow the port through the host firewall if needed. This backend provides no authentication or encryption; do not expose it to untrusted networks or the public Internet.

The desktop backend uses the Python installation's Tk support and Pillow. Linux may require installing the matching Tk package (for example, `python3-tk`) and running in a graphical session. GUI modules are imported only when the window backend is constructed.

For the validated Waveshare hardware combination, installation, SPI/GPIO configuration, device permissions, physical smoke testing, troubleshooting, and driver provenance, see the [Waveshare display installation guide](src/refrain/display/vendor/waveshare/README.md). Hardware-dependent behavior must be validated on the physical panel; mocked tests do not establish hardware support.

To display two PNG files in the same responsive window and close cleanly, run:

```sh
python examples/display_window.py first.png second.png
```

The example waits for Enter between updates while the window continues to process GUI events. It does not perform content selection or image preparation.

To test the HTTP backend independently of the application controller, provide two PNG images:

```sh
python examples/image_server.py first.png second.png
```

Open the printed URL in a browser to view the first image, then press Enter in the terminal to replace it with the second. Use `--host 0.0.0.0` to make the test server reachable from a trusted LAN; visit the server's LAN IP in the browser. The example defaults to port `8080`; override it with `--port` if that port is occupied.

## Rendering a literary composition

The shared renderer accepts an existing Pillow image, resolved quotation/source/attribution content, a quotation font and optional source and attribution fonts, a normalized presentation region, a built-in presentation style, and quotation font-size bounds. `layout_composition` fits all present fields—including the complete mixed-face unified byline—once and vertically centers the complete composition as one group. Its keyword-only `byline_gap_factor` defaults to `1.20` times the fitted quotation font size; zero is valid, and no gap is reserved when the byline is absent. `render_reveal_stages` then renders requested cumulative visibility stages from that same geometry. Unrevealed byline text uses deterministic pixel distortion by default; the dash and separator punctuation remain visible in the quotation face. Attribution uses a restrained gray tone; the byline is centered in `centered` style and right-aligned in `left-aligned` style. The `left-aligned` style aligns quotation lines at a common left edge while centering the whole quotation block within the presentation region. The keyword-only `concealment` parameter accepts only `"pixel-distortion"`. Rendering returns copies and leaves the supplied background unchanged. A `QuotationRenderError` is raised for invalid inputs or content that cannot fit. See [Presentation and rendering](docs/ARCHITECTURE.md#presentation-and-rendering) and [Presentation region](docs/CONTENT_FORMAT.md#presentation-region) for the authoritative behavior and geometry.

```python
from importlib.resources import files

from PIL import Image

from refrain import (
    CompositionVisibility,
    LiteraryComposition,
    PresentationRegion,
    ResolvedFont,
    layout_composition,
    render_reveal_stages,
)

resource = files("refrain").joinpath("assets", "fonts", "lora", "Lora-Regular.ttf")
with resource.open("rb") as font_file:
    font = ResolvedFont("lora", font_file.read())

background = Image.new("RGB", (1600, 1200), "#FFFFFF")
region = PresentationRegion(x=0.1, y=0.12, width=0.8, height=0.76)
composition = LiteraryComposition(
    quotation="A resolved quotation is fitted to the supplied page.",
    source="A Book of Examples",
    attribution="An Example Author",
)

for style in ("centered", "left-aligned"):
    layout = layout_composition(
        composition,
        font,
        region,
        background.size,
        min_font_size=28,
        max_font_size=100,
        presentation_style=style,
        byline_gap_factor=1.20,
    )
    stages = render_reveal_stages(
        background,
        font,
        layout,
        (
            CompositionVisibility(),
            CompositionVisibility(source=True),
            CompositionVisibility(source=True, attribution=True),
        ),
        concealment="pixel-distortion",
    )
    for index, image in enumerate(stages):
        image.save(f"{style}-{index}.png")
```

The complete byline reads `— An Example Author, A Book of Examples`; if either optional field is absent, its separator is omitted. A `CompositionLayout` keeps quotation and byline geometry identical across stages. To generate inspectable 1600 × 1200 examples for all four optional-field combinations, both styles, and all three bundled fonts, run `python examples/render_quotation_previews.py /tmp/refrain-previews`. Output is grouped by font identifier. To compare another spacing while keeping the layout fixed across reveal stages, pass a different `byline_gap_factor` to `layout_composition`; concealment remains deterministic pixel distortion.

## Preparing images from a daily snapshot

`prepare_daily_images(snapshot, stages, font_registry, background_registry=None, decoration_registry=None)` produces complete RGB Pillow images from a committed `DailySnapshot` and an explicit sequence of cumulative `CompositionVisibility` stages. Pass the effective background and decoration registries to resolve selected resources. A missing or unusable background warns and leaves the paper-white base; a missing or unusable decoration warns and omits the overlay. Neither is reselected during preparation. Composition is paper-white, background, decoration, then literary text, using the snapshot's committed effective region. Font and geometry are resolved once and reused for all stages. Missing or invalid required presentation data, the absence of a usable font, and content that cannot fit raise `DailyImagePreparationError`. Preparation does not load content or modify persistent state. See the [committed daily presentation data contract](docs/ARCHITECTURE.md#committed-daily-presentation-data).

```python
from refrain import CompositionVisibility, PersistentStateStore, load_application_config, prepare_daily_images

state = PersistentStateStore("/absolute/path/chosen-for-this-installation/state.json").load()
if state is None:
    raise RuntimeError("there is no committed daily snapshot")
config = load_application_config("config.yaml")

metadata = state.snapshot.presentation_metadata
source_revealed = False
stages = [CompositionVisibility()]
if metadata.get("source") is not None:
    source_revealed = True
    stages.append(CompositionVisibility(source=True))
if metadata.get("attribution") is not None:
    stages.append(CompositionVisibility(source=source_revealed, attribution=True))
images = prepare_daily_images(state.snapshot, tuple(stages), config.fonts, config.backgrounds, config.decorations)
for index, image in enumerate(images):
    image.save(f"daily-stage-{index}.png")
```

Run `python examples/prepare_daily_snapshot.py /tmp/refrain-daily-images` to generate full-resolution inspectable images from synthetic committed snapshot data without display hardware.

## Storing prepared images

`PreparedImageArtifactStore(root)` owns derived artifacts under a caller-chosen absolute directory, separate from authoritative state and user content. The root and its ancestors must not be symbolic links or directory junctions. `store(revision, snapshot, images)` accepts a positive committed `PersistentState.revision`, its `DailySnapshot`, and a nonempty ordered sequence of complete Pillow images. Images must match `snapshot.layout.image_size` and share one supported mode: `1`, `L`, `LA`, `RGB`, or `RGBA`. They are stored losslessly as PNGs without conversion.

Using `state`, `stages`, and `images` from the preparation example:

```python
from refrain import PreparedImageArtifactStore

root = "/absolute/path/chosen-for-this-installation/prepared-images"
store = PreparedImageArtifactStore(root)
try:
    artifacts = store.store(state.revision, state.snapshot, images)
finally:
    for image in images:
        image.close()

# Later, including after a restart; the caller supplies the expected stage count.
artifacts = PreparedImageArtifactStore(root).load(
    state.revision, state.snapshot, stage_count=len(stages)
)
if artifacts is None:
    raise RuntimeError("no prepared artifact directory exists for this revision")
with artifacts.load_stage(0) as image:
    image.save("reloaded-stage-0.png")  # Or pass this complete image to a consumer.

# Explicitly coordinated with other artifact users; never runs automatically.
store.cleanup(current_revision=state.revision)
```

`load` validates the complete set one image at a time and returns a `PreparedImageArtifactSet` containing metadata and `stage_paths`, not retained decoded images. `load_stage(index)` returns one caller-owned image and rechecks its integrity; close it after use. Advancing reveal progress does not change artifact identity. A matching revision with a different snapshot is rejected.

An absent revision directory returns `None`; an existing but incomplete, damaged, unsupported, or mismatched set raises `ArtifactValidationError`. Artifact-root access failures raise `ArtifactAccessError`; filesystem write failures raise `ArtifactWriteError`, whose `published` flag distinguishes failure before manifest replacement from publication with uncertain directory durability. Reload after a published failure before deciding what to retry. Cleanup failures raise `ArtifactCleanupError` without invalidating the current set. These exceptions share `ArtifactStoreError`; invalid API arguments raise `ValueError` or `TypeError`. Storage never regenerates images or modifies committed state.

The caller must serialize store operations and coordinate cleanup with all users of returned stage paths. Cleanup preserves the current revision directory even if invalid, skips unrelated entries and link-bearing trees, and removes recognized obsolete revisions and abandoned root-level transactions. See [Prepared image files](docs/ENGINEERING.md#prepared-image-files) for layout, publication, and durability details.

## Recovering prepared images

`recover_prepared_daily_images(state, artifact_store, stages, font_registry, background_registry=None, decoration_registry=None)` reuses a complete valid set for the committed revision and snapshot. Pass the effective background and decoration registries for regeneration. A missing committed background uses paper-white; a missing decoration is omitted. Valid artifacts are reused without resolving or loading resources. `stages` must be the full ordered sequence of cumulative `CompositionVisibility` values, ending with all available fields revealed; it is validated before reuse and supplies the expected stage count. Pass the same sequence used to prepare the stored set: the existing artifact format records its count, not individual visibility definitions. If the set is absent or invalid, recovery prepares and stores every stage from `state.snapshot`, resolving its committed resource identifiers without reselection or recalculating the saved region. Recovery does not load content, alter committed identifiers or layout, or clean artifact directories.

```python
from refrain import (
    CompositionVisibility,
    PreparedImageArtifactStore,
    load_application_config,
    recover_prepared_daily_images,
)

config = load_application_config("config.yaml")
store = PreparedImageArtifactStore("/absolute/path/chosen-for-this-installation/prepared-images")
artifacts = recover_prepared_daily_images(state, store, stages, config.fonts, config.backgrounds, config.decorations)

# The returned set contains validated paths, not retained decoded images.
with artifacts.load_stage(0) as image:
    image.save("recovered-stage-0.png")
```

Recovery closes all generated Pillow images after storage, including when storage fails. Rendering errors are reported without changing the committed selection; `ArtifactAccessError` is not treated as a cache miss, and `ArtifactWriteError.published` remains available to callers. Existing validated artifacts are returned without rendering or rewriting.

## Loading content

`load_content_library` reads `.yaml` and `.yml` files recursively from a supplied directory. It returns a tuple of accepted `ContentEntry` objects; each entry contains its metadata, presentation style, eligibility rules, reveal overrides, and separate `Quotation` candidates. Each quotation retains its original `text` and has a normalized `identity` for repetition tracking.

Validation is performed by `load_content_library`; directly constructing `ContentEntry`, `Quotation`, or other model dataclasses does not validate their fields.

```python
from refrain import ContentLibraryError, load_content_library

try:
    entries = load_content_library("examples/content")
except ContentLibraryError as error:
    for diagnostic in error.diagnostics:
        print(diagnostic)
```

Malformed files, invalid entries, and all entries participating in a duplicate-identifier conflict are excluded with actionable warnings; unrelated accepted entries remain available. A `ContentLibraryError` indicates failed source discovery or a directory with no accepted quotations. Rejected-content warnings are emitted through Python logging. The loader validates intrinsic content rules only: eligibility is not evaluated for a date, reveal times are not resolved against application configuration, and font preferences are not checked against a font registry.

See [`examples/content/sample.yaml`](examples/content/sample.yaml) for an example entry and [`docs/CONTENT_FORMAT.md`](docs/CONTENT_FORMAT.md) for the authoritative YAML specification.

## Evaluating quotation eligibility

`build_eligible_quotation_pool` evaluates the entries for an explicit display date and returns the candidates at the winning specificity. Each candidate exposes its quotation text and identity, priority, and containing entry with its metadata. The result's `specificity` is `None` when no quotations are eligible. See [Content eligibility and selection](docs/ARCHITECTURE.md#content-eligibility-and-selection) for the authoritative precedence rules.

```python
from datetime import date

from refrain import build_eligible_quotation_pool, load_content_library

entries = load_content_library("examples/content")
pool = build_eligible_quotation_pool(entries, date(2024, 2, 29))

for candidate in pool.candidates:
    print(candidate.text, candidate.entry.source, candidate.priority)
```

`select_quotation` proposes a repetition-aware selection without changing the input history. Its proposed history is not committed; the application must commit the selected quotation and history together. See [Content eligibility and selection](docs/ARCHITECTURE.md#content-eligibility-and-selection) for the authoritative selection policy.

```python
from random import Random

from refrain import select_quotation

history = {"A previously selected normalized quotation."}
proposal = select_quotation(pool, history, random_source=Random())

if proposal.selected_candidate is not None:
    candidate = proposal.selected_candidate
    proposed_history = proposal.proposed_repetition_history
```

## Persisting and recovering a selection

`PersistentStateStore` distinguishes an uninitialized location (`load()` returns `None`) from invalid existing state (a `StateRecoveryError`). It supports operational state format 5; formats 1 through 4 are rejected with an actionable compatibility error and remain untouched, without migration. Its scheduling context contains the display date and day-start time, not a timezone identifier. A commit requires the caller's provisional selection and a complete `DailySnapshot` containing resolved presentation, scheduling, effective layout and region, `font_identifier`, `background_identifier`, and `decoration_identifier`. Resource bytes, paths, and content digests are not embedded in state. Choose an absolute state-file path appropriate to the installation.

The example assumes the caller has already recognized a display-day transition. Compare state revisions, not display dates, when deciding whether a proposal is stale; clock adjustments can legitimately lead to a later commit for a previously used date.

```python
from datetime import date
from pathlib import Path
from random import Random

from refrain import (
    DailySnapshot,
    GlobalHistoryStore,
    GlobalHistoryWriteError,
    PersistentStateStore,
    SchedulingContext,
    build_eligible_quotation_pool,
    load_content_library,
    load_application_config,
    select_quotation,
)

state_path = Path("/absolute/path/chosen-for-this-installation/state.json")
config = load_application_config("config.yaml")
display_date = date(2026, 10, 26)
store = PersistentStateStore(state_path)
previous = store.load()

if selection_boundary_recognized:
    entries = load_content_library("examples/content")
    library_identities = {quotation.identity for entry in entries for quotation in entry.quotations}
    repetition_history = set() if previous is None else set(previous.repetition_history)
    repetition_history.intersection_update(library_identities)
    base_revision = 0 if previous is None else previous.revision
    pool = build_eligible_quotation_pool(entries, display_date)
    proposal = select_quotation(
        pool,
        repetition_history,
        random_source=Random(),
        base_revision=base_revision,
    )
    candidate = proposal.selected_candidate

    if candidate is not None:
        # Assume selection policy resolved the font to "lora" and background to "aged-paper".
        snapshot = DailySnapshot(
            quotation_text=candidate.text,
            quotation_identity=candidate.identity,
            font_identifier="lora",
            background_identifier="aged-paper",
            decoration_identifier="none",
            presentation_metadata={
                "source": candidate.entry.source,
                "attribution": candidate.entry.attribution,
                "presentation_style": candidate.entry.presentation_style,
            },
            reveal_schedule={
                "quotation": config.day_start.strftime("%H:%M"),
                "source": config.reveal.source.strftime("%H:%M"),
                "attribution": config.reveal.attribution.strftime("%H:%M"),
            },
            layout={
                "image_size": (1600, 1200),
                "presentation_region": {
                    "x": config.presentation_region.x,
                    "y": config.presentation_region.y,
                    "width": config.presentation_region.width,
                    "height": config.presentation_region.height,
                },
                "min_font_size": config.min_font_size,
                "max_font_size": config.max_font_size,
            },
            scheduling=SchedulingContext(
                display_date,
                config.day_start.strftime("%H:%M"),
            ),
        )
        committed = store.commit(proposal, snapshot)
        history = GlobalHistoryStore("/absolute/path/chosen-for-this-installation/global-history.jsonl")
        try:
            history.record(committed)
        except GlobalHistoryWriteError as error:
            print(f"Committed selection was not recorded in global history: {error}")

recovered = PersistentStateStore(state_path).load()
```

### Persisting reveal progress

Reveal progress belongs to a selection revision, separately from its immutable snapshot. The caller supplies the stage; the store does not evaluate the schedule or current time.

```python
store = PersistentStateStore(state_path)
current = store.load()
if current is not None:
    advanced = store.advance_reveal_progress(expected_revision=current.revision, stage=1)

    # After an application restart:
    recovered = PersistentStateStore(state_path).load()
    assert recovered.snapshot == current.snapshot
    assert recovered.highest_reveal_stage == advanced.highest_reveal_stage
    assert recovered.highest_reveal_stage >= 1
```

Stages must be nonnegative integers (not booleans). Same or earlier-stage requests do not rewrite state. An obsolete revision raises `StateCommitError`, even for an earlier-stage request. A new `commit` starts at `initial_reveal_stage=0` unless the caller supplies another initial stage; retrying a committed selection preserves subsequent progress. Reveal advancement and retries preserve the selection revision and repetition history.

Serialize all writes to the same state path. If a write raises `StateCommitError`, inspect its `published` attribute and reload the authoritative state before retrying; a published update may have taken effect even when durability confirmation failed.

The file format and atomic-replacement durability guarantees and limitations are documented in [Persistent storage](docs/ENGINEERING.md#persistent-storage).
