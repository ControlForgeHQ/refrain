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

## Loading content

`load_content_library` reads `.yaml` and `.yml` files recursively from a supplied directory. It returns a tuple of validated `ContentEntry` objects; each entry contains its metadata, eligibility rules, reveal overrides, and separate `Quotation` candidates. Each quotation retains its original `text` and has a normalized `identity` for repetition tracking.

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
            presentation_metadata={"source": candidate.entry.source, "attribution": candidate.entry.attribution},
            reveal_schedule={
                "quotation": config.reveal.quotation.isoformat(),
                "source": config.reveal.source.isoformat(),
                "attribution": config.reveal.attribution.isoformat(),
            },
            layout={
                "quotation_region": {
                    "x": config.quotation_region.x,
                    "y": config.quotation_region.y,
                    "width": config.quotation_region.width,
                    "height": config.quotation_region.height,
                }
            },
            scheduling=SchedulingContext(display_date, str(config.timezone), config.day_start.isoformat()),
        )
        store.commit(proposal, snapshot)

recovered = PersistentStateStore(state_path).load()
```

The file format and atomic-replacement durability guarantees and limitations are documented in [Persistent storage](docs/ENGINEERING.md#persistent-storage).
