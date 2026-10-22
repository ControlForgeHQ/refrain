# refrain
An open-source e-paper display for rotating quotations, progressive reveals, and interactive content.

## Development setup

Refrain's content loader is hardware-independent. Python 3.10 or newer is required.

Create an isolated environment and install the package with its development tools:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --editable '.[dev]'
```

Run the automated validation commands from the repository root:

```sh
.venv/bin/black --check src tests
.venv/bin/ruff check src tests
.venv/bin/pytest
```

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
