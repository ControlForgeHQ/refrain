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

`load_application_config` reads and validates `config.yaml`, returning resolved paths, the effective font registry, and the settings required by downstream components. Relative content and user-font paths are based on the configuration file's directory. See [`examples/config.yaml`](examples/config.yaml) for a bundled-font example and [`docs/CONTENT_FORMAT.md`](docs/CONTENT_FORMAT.md) for the authoritative configuration specification.

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

## Running Refrain

`python -m refrain` runs continuously, automatically presenting progressive reveals and selecting new quotations at observed display-day boundaries. All three locations are required and are never inferred from a user's home directory or installation layout:

```sh
.venv/bin/python -m refrain \
  --config examples/config.yaml \
  --state /path/to/refrain/state.json \
  --artifacts /path/to/refrain/artifacts
```

- `--config` is the application configuration file; relative content and font paths resolve against its directory.
- `--state` is the persistent selection-state file. It is created on first use, and its parent directory is created if needed.
- `--artifacts` is the directory for derived prepared images. It is separate from state and content and may be regenerated from committed state.

With no committed state, the command selects a quotation for the current display date, commits the complete daily snapshot and histories, prepares the reveal images, and presents the stage required at the current time. With existing state, it recovers the committed selection without needing its original content library and reuses valid prepared images (regenerating missing or invalid ones). Missed reveals advance directly to the latest required stage; backward clock adjustments never hide information already revealed.

The continuous runtime keeps one display backend active across updates. It waits interruptibly for scheduling events, periodically checking for wall-clock adjustments, and retries recoverable content, storage, preparation, and display failures with monotonic delays increasing from 1 to at most 60 seconds. A failed presentation never causes reselection. Invalid application configuration or corrupted authoritative state terminates with status 1 rather than retrying indefinitely. Configuration is loaded once; content is reloaded only when a new selection is needed. After recovering the active image set, the coordinator removes obsolete revision artifacts using the store's coordinated cleanup; the active revision is retained.

Press Ctrl+C or send SIGTERM to stop. Shutdown interrupts scheduling and retry waits, releases the backend, and preserves state and prepared images without intentionally clearing retained e-paper content. The `window` and `image-server` backends remain operational throughout execution and close on shutdown; HTTP serving stops at that point. Synchronous preparation or display operations finish before shutdown can release their resources. Physical panel behavior still requires hardware validation.

### One-shot startup and diagnostics

Add `--once` to run only the startup-and-presentation workflow:

```sh
.venv/bin/python -m refrain \
  --config examples/config.yaml \
  --state /path/to/refrain/state.json \
  --artifacts /path/to/refrain/artifacts \
  --once
```

One-shot execution does not schedule future updates or retry failures. For `window` and `image-server`, it holds the initial presentation open until Ctrl+C; the Waveshare panel retains its image after the command exits. The Python API also preserves `run_startup(...)` for one-shot use and exposes `run_application(..., shutdown_event=event)` for continuous operation with an explicit `threading.Event`.

### Recovery limitation

Boundary observations exist only during the current process lifetime. After an interruption spanning a display-day transition, the stored scheduling context and an isolated startup timestamp cannot reliably distinguish a missed transition from a clock correction. Recovery therefore conservatively retains the committed selection, presenting its latest required reveal stage, until a subsequent boundary is actually observed. During continuous execution, a forward jump across several display days selects only for the currently appropriate date; a backward correction preserves the current selection until a newly observed boundary. See [boundary recognition](docs/ARCHITECTURE.md#boundary-recognition).

## Display backend selection

Every application configuration must explicitly set `display.backend`. Use `window` for development on a graphical Windows or Linux desktop; use `waveshare-13in3-e` on a supported Raspberry Pi with the physical panel connected; or use `image-server` to serve the current complete image to HTTP clients. See [Display backend](docs/CONTENT_FORMAT.md#display-backend) for the configuration contract.

The image server defaults to loopback-only access at `http://127.0.0.1:8080/display/current`. Configure it explicitly to accept connections from other devices on a trusted local network:

```yaml
display:
  backend: "image-server"
  image-server:
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

The shared renderer accepts an existing Pillow image, resolved quotation/source/attribution content, a resolved font, a normalized presentation region, a built-in presentation style, and quotation font-size bounds. `layout_composition` fits all present fields—including the complete unified byline—once and vertically centers the complete composition as one group. Its keyword-only `byline_gap_factor` defaults to `1.20` times the fitted quotation font size; zero is valid, and no gap is reserved when the byline is absent. `render_reveal_stages` then renders requested cumulative visibility stages from that same geometry. Unrevealed byline text uses deterministic pixel distortion by default; the dash and separator punctuation remain visible. Attribution uses a restrained gray tone; the byline is centered in `centered` style and right-aligned in `left-aligned` style. The `left-aligned` style aligns quotation lines at a common left edge while centering the whole quotation block within the presentation region. The keyword-only `concealment` parameter accepts only `"pixel-distortion"`. Rendering returns copies and leaves the supplied background unchanged. A `QuotationRenderError` is raised for invalid inputs or content that cannot fit. See [Presentation and rendering](docs/ARCHITECTURE.md#presentation-and-rendering) and [Presentation region](docs/CONTENT_FORMAT.md#presentation-region) for the authoritative behavior and geometry.

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

`prepare_daily_images(snapshot, stages)` produces complete RGB Pillow images from a committed `DailySnapshot` and an explicit sequence of cumulative `CompositionVisibility` stages. It uses only the snapshot's literary fields, presentation metadata, layout values, and embedded font bytes; missing or invalid required presentation data and content that cannot fit raise `DailyImagePreparationError`. It does not load current configuration or content, or modify persistent state. See the [committed daily presentation data contract](docs/ARCHITECTURE.md#committed-daily-presentation-data).

```python
from refrain import CompositionVisibility, PersistentStateStore, prepare_daily_images

state = PersistentStateStore("/absolute/path/chosen-for-this-installation/state.json").load()
if state is None:
    raise RuntimeError("there is no committed daily snapshot")

metadata = state.snapshot.presentation_metadata
source_revealed = False
stages = [CompositionVisibility()]
if metadata.get("source") is not None:
    source_revealed = True
    stages.append(CompositionVisibility(source=True))
if metadata.get("attribution") is not None:
    stages.append(CompositionVisibility(source=source_revealed, attribution=True))
images = prepare_daily_images(state.snapshot, tuple(stages))
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

`recover_prepared_daily_images(state, artifact_store, stages)` reuses a complete valid set for the committed revision and snapshot. `stages` must be the full ordered sequence of cumulative `CompositionVisibility` values, ending with all available fields revealed; it is validated before reuse and supplies the expected stage count. Pass the same sequence used to prepare the stored set: the existing artifact format records its count, not individual visibility definitions. If the set is absent or invalid, recovery prepares and stores every stage from `state.snapshot`. It never loads content or configuration, changes persistent state, or cleans artifact directories.

```python
from refrain import (
    CompositionVisibility,
    PreparedImageArtifactStore,
    recover_prepared_daily_images,
)

store = PreparedImageArtifactStore("/absolute/path/chosen-for-this-installation/prepared-images")
artifacts = recover_prepared_daily_images(state, store, stages)

# The returned set contains validated paths, not retained decoded images.
with artifacts.load_stage(0) as image:
    image.save("recovered-stage-0.png")
```

Recovery closes all generated Pillow images after storage, including when storage fails. Rendering errors are reported without changing the committed selection; `ArtifactAccessError` is not treated as a cache miss, and `ArtifactWriteError.published` remains available to callers. Existing validated artifacts are returned without rendering or rewriting.

## Loading content

`load_content_library` reads `.yaml` and `.yml` files recursively from a supplied directory. It returns a tuple of validated `ContentEntry` objects; each entry contains its metadata, presentation style, eligibility rules, reveal overrides, and separate `Quotation` candidates. Each quotation retains its original `text` and has a normalized `identity` for repetition tracking.

Validation is performed by `load_content_library`; directly constructing `ContentEntry`, `Quotation`, or other model dataclasses does not validate their fields.

```python
from refrain import ContentLibraryError, load_content_library

try:
    entries = load_content_library("examples/content")
except ContentLibraryError as error:
    for diagnostic in error.diagnostics:
        print(diagnostic)
```

The loader rejects the entire library if any entry is invalid. Each diagnostic identifies its file and field. It validates intrinsic content rules only: eligibility is not evaluated for a date, reveal times are not resolved against application configuration, and font preferences are not checked against a font registry.

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

`PersistentStateStore` distinguishes an uninitialized location (`load()` returns `None`) from invalid existing state (a `StateRecoveryError`). A commit requires the caller's provisional selection and a complete `DailySnapshot` containing already-resolved presentation, scheduling, layout, and font information. Choose an absolute state-file path appropriate to the installation.

The example assumes the caller has already recognized a display-day transition. Compare state revisions, not display dates, when deciding whether a proposal is stale; clock adjustments can legitimately lead to a later commit for a previously used date.

```python
from datetime import date
from pathlib import Path
from random import Random

from refrain import (
    DailySnapshot,
    PersistentStateStore,
    ResolvedFont,
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
    repetition_history = () if previous is None else previous.repetition_history
    base_revision = 0 if previous is None else previous.revision
    entries = load_content_library("examples/content")
    pool = build_eligible_quotation_pool(entries, display_date)
    proposal = select_quotation(
        pool,
        repetition_history,
        random_source=Random(),
        base_revision=base_revision,
    )
    candidate = proposal.selected_candidate

    if candidate is not None:
        # Assume the application's policy resolved this candidate to "lora".
        font_resource = config.fonts["lora"]
        with font_resource.path.open("rb") as font_file:
            font = ResolvedFont(font_resource.identifier, font_file.read())
        snapshot = DailySnapshot(
            quotation_text=candidate.text,
            quotation_identity=candidate.identity,
            font=font,
            presentation_metadata={
                "source": candidate.entry.source,
                "attribution": candidate.entry.attribution,
                "presentation_style": candidate.entry.presentation_style,
            },
            reveal_schedule={
                "quotation": config.reveal.quotation.strftime("%H:%M"),
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
                str(config.timezone),
                config.day_start.strftime("%H:%M"),
            ),
        )
        store.commit(proposal, snapshot)

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

Stages must be nonnegative integers (not booleans). Same or earlier-stage requests do not rewrite state. An obsolete revision raises `StateCommitError`, even for an earlier-stage request. A new `commit` starts at `initial_reveal_stage=0` unless the caller supplies another initial stage; retrying a committed selection preserves subsequent progress. Neither advancement nor its retries change the selection revision or either history.

Serialize all writes to the same state path. If a write raises `StateCommitError`, inspect its `published` attribute and reload the authoritative state before retrying; a published update may have taken effect even when durability confirmation failed.

The file format and atomic-replacement durability guarantees and limitations are documented in [Persistent storage](docs/ENGINEERING.md#persistent-storage).
