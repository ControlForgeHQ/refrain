# Command-line usage

## Resident runtime control

The primary `refrain --refresh` command requires an already-running normal Refrain instance. It asks that runtime to republish the presentation currently required by scheduling to every configured destination. It does not restore historical pre-preview pixels: if reveal progression advanced, refresh publishes the current reveal stage.

Refresh is a synchronous one-shot control request, not another resident runtime. Refrain reports visible progress before waiting and remains attached until publication to all configured destinations completes or fails. The command succeeds only if every destination succeeds. If the operation cannot be admitted safely at once, it is rejected as busy rather than queued. Refresh does not start Refrain or access configured backends independently.

## Presentation viewer

`refrain-viewer` renders one fully revealed Refrain presentation. With no arguments it uses the standard configuration, selects the medium built-in `@preview` quotation, and opens a simple local window:

```text
refrain-viewer
```

Select a content entry and its 1-based quotation number:

```text
refrain-viewer --entry johnson-maggie:6
```

Override a registered presentation choice:

```text
refrain-viewer --decoration simple-border
```

Constrain automatic quotation fitting with design-canvas pixel bounds:

```text
refrain-viewer --min-font-size 48 --max-font-size 120
```

Select an alternate configuration and save the final PNG:

```text
refrain-viewer --config ./experimental.yaml --background aged-paper --output preview.png
```

`--output` saves the final output image without opening a window. Add `--window` to save and display the same presentation. In ordinary inspection and export modes, the viewer does not use configured display backends or runtime persistence.

### Push to configured destinations

The final intended push form is:

```text
refrain-viewer [presentation overrides...] --push TARGET
```

`TARGET` is either `all` or one canonical destination identifier discovered from the running normal Refrain instance. `all` selects every configured destination. Identifiers are supplied by the runtime and are opaque: the viewer does not infer a backend type or output behavior from their names. A backend with one output may be identified by its backend ID; a backend with multiple outputs may expose distinct IDs such as `image-server:default`.

Push requires a running normal Refrain instance. The viewer asks it for the selected destination identifiers and their aspect ratios and requested resolutions, renders complete image variants using its own selected configuration, content, assets, and presentation overrides, then submits those images to the runtime. The runtime owns destination geometry and publication; the viewer owns the preview pixels. Destinations with identical output specifications may share one rendered variant. Discovery does not reserve a destination, so publication may be rejected as busy if runtime work begins while the viewer renders.

`--push` is mutually exclusive with `--window`, `--output`, `--aspect`, and `--resolution`; output geometry in push mode comes entirely from the selected runtime destinations. Presentation options remain available, including `--config`, `--entry`, `--font`, `--quotation-face`, `--source-face`, `--attribution-face`, `--background`, `--decoration`, `--text-color`, `--tint`, `--style`, `--qr` / `--no-qr`, `--min-font-size`, `--max-font-size`, and `--debug-layout`.

Push is synchronous. Before waiting for potentially slow publication, the viewer identifies the selected destination set and reports visible progress. It remains attached until publication to every selected destination has completed or failed; a zero exit status means every selected destination succeeded. Busy requests are rejected without queuing or partial publication. A changed destination or output specification is rejected rather than inferred or resized.
