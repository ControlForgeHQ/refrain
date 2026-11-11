# Command-line usage

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

Select an alternate configuration and save the final PNG:

```text
refrain-viewer --config ./experimental.yaml --background aged-paper --output preview.png
```

`--output` saves the final output image without opening a window. Add `--window` to save and display the same presentation. The viewer does not use configured display backends or runtime persistence.
