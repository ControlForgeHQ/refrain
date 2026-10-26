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
