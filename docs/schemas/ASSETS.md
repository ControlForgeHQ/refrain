# Assets

This document specifies Refrain's font bundles, background assets, and decoration manifests, including resource identifiers, presentation preferences, image layers, geometry, and validation requirements.

## YAML manifests

Use UTF-8 and exactly one YAML document containing one top-level mapping. Manifest filenames are `font.yaml`, `background.yaml`, and `decoration.yaml`.

Use ordinary mappings, sequences, strings, integers, and booleans. Mapping keys must be strings. Custom tags, executable constructors, anchors, aliases, merge keys, duplicate keys, and implicit application-specific expressions are unsupported. Use spaces for indentation; two spaces are recommended. Quote values that could otherwise parse as dates, numbers, booleans, or null when strings are required.

All three manifests require `format: 1`, where `1` is an integer, and a valid `id`. Booleans do not satisfy integer fields. Explicit null is invalid unless a field's recovery rule handles it.

Unknown manifest and layer fields produce warnings and are ignored unless a stricter rule is stated below. They do not define extensions or drawing instructions.

## Resource identifiers and discovery

Resource identifiers are nonempty, case-sensitive ASCII strings matching `[A-Za-z0-9][A-Za-z0-9_-]*`. Directory names do not determine manifest-defined identifiers. The same identifier may be used in different resource categories.

Refrain discovers bundled resources through package resources and user resources recursively under these directories beside the selected configuration file:

| Category | User directory | Resource form |
|---|---|---|
| Font bundles | `assets/fonts/` | A directory containing `font.yaml`. |
| Backgrounds | `assets/backgrounds/` | A standalone PNG or a directory containing `background.yaml`. |
| Decorations | `assets/decorations/` | A directory containing `decoration.yaml`. |

An alternate configuration file supplies its own containing directory as the user-assets root. The working directory, standard configuration directory, and content-library location do not supply additional user assets.

A recognized package is a discovery boundary. Its internal images are not registered as standalone backgrounds, and discovery does not continue into nested packages within it. Discovery does not follow symbolic-link directories, manifest files, or standalone image files.

Every successfully registered asset is available by identifier independently of default-pool membership. Discovery alone does not add an asset to a configured pool. Resource and pool declarations are specified in [Application Configuration](CONFIGURATION.md#resources-and-named-pools).

`none` is reserved and cannot be registered as a font, background, or decoration identifier. In background and decoration preferences, `"none"` requests absence. It is not a font-suppression value.

### Identifier collisions

Custom assets cannot shadow bundled identifiers. A readable bundled manifest with a syntactically valid identifier claims that identifier even if another manifest field or referenced resource makes the asset unusable. A bundled standalone background similarly claims its valid filename-stem identifier. An identifier is not reserved once no bundled resource claims it.

All custom resources sharing an identifier in one category are excluded. Diagnostics list their locations deterministically; filesystem enumeration order must not select a custom winner. Unrelated resources remain usable.

### Resource paths

Manifest file references are nonempty relative paths resolved from the manifest directory, using forward slashes. Referenced files must exist, be readable, and remain within that package.

Absolute paths, Windows drive-qualified paths, backslash separators, parent traversal through `..`, and references escaping the package, including symbolic-link escapes, are invalid. A file reference is not an arbitrary external-path registration interface.

Font paths use `.ttf` or `.otf`; layer image paths use `.png`. Files must also pass the corresponding font or image validation; a matching extension alone is insufficient.

## Font bundles

Each bundle contains a `font.yaml` manifest and its referenced font files.

| Field | Type | Required | Default when omitted |
|---|---|---|---|
| `format` | Integer `1` | Yes | None. |
| `id` | Resource identifier | Yes | None. |
| `faces` | Nonempty mapping of face identifiers to font paths | Yes | None. |
| `font_faces` | Literary-role preference mapping | No | No role preferences. |

Face identifiers use the shared identifier syntax. A bundle must contain a usable face named `regular`. Files need not all belong to one typographic family. Font files must be readable and loadable by the Pillow renderer.

An invalid face name or structurally invalid required manifest data excludes the bundle. A missing, invalid, or unusable `regular` face excludes it. An unusable optional face is diagnosed and excluded individually, leaving an otherwise usable bundle available. Every referenced face must obey the package path-confinement rules.

Bundled font directories retain their applicable license and copyright files. Redistribution requirements are described in [Engineering](../ENGINEERING.md#font-loading-and-resolution).

### Literary-role face preferences

The optional `font_faces` mapping in a font or decoration manifest accepts only `quotation`, `source`, and `attribution`. Each role is optional; an empty mapping expresses no preferences. Values are case-sensitive face identifiers, not file paths, bundle identifiers, or pool references.

A malformed mapping, unknown role, or invalid face identifier produces a warning and causes the complete preference mapping to be ignored without excluding the containing asset. A syntactically valid preference may name a face absent from the selected bundle.

The `faces` mapping registers files; `font_faces` expresses role preferences. A role preference does not select a bundle. Winning-role resolution and fallback to that bundle's `regular` face are specified in [Architecture](../ARCHITECTURE.md#font-selection).

### Bundled font bundles

The packaged manifests declare these bundle and face identifiers:

| Bundle | Faces |
|---|---|
| `alegreya` | `regular`, `italic`, `medium`, `medium-italic`, `semi-bold`, `semi-bold-italic`, `bold`, `bold-italic`, `extra-bold`, `extra-bold-italic`, `black`, `black-italic` |
| `libre-baskerville` | `regular`, `italic`, `medium`, `medium-italic`, `semi-bold`, `semi-bold-italic`, `bold`, `bold-italic` |
| `lora` | `regular`, `italic`, `medium`, `medium-italic`, `semi-bold`, `semi-bold-italic`, `bold`, `bold-italic` |
| `orbitron` | `regular`, `medium`, `semi-bold`, `bold`, `extra-bold`, `black` |
| `source-sans-3` | `regular`, `italic`, `extra-light`, `extra-light-italic`, `light`, `light-italic`, `medium`, `medium-italic`, `semi-bold`, `semi-bold-italic`, `bold`, `bold-italic`, `extra-bold`, `extra-bold-italic`, `black`, `black-italic` |

Registration depends on successful validation. These bundles do not constrain the face names available in custom bundles.

## Background assets

### Standalone backgrounds

A standalone PNG's filename stem supplies its identifier. For example, `assets/backgrounds/paper.png` registers `paper`. It must be a readable, single-frame RGB or RGBA PNG with positive dimensions.

A standalone background uses centered `cover` and supplies no background-level color preferences. Its dimensions need not match any output resolution.

The bundled standalone background identifiers are `aged-paper`, `canvas`, and `marble`.

### Background manifests

A packaged background contains `background.yaml` and its referenced PNG files.

| Field | Type | Required | Default when omitted |
|---|---|---|---|
| `format` | Integer `1` | Yes | None. |
| `id` | Resource identifier | Yes | None. |
| `layers` | Nonempty ordered sequence of background-layer mappings | Yes | None. |
| `text_color` | Color preference | No | No preference. |
| `decoration_color` | Color preference | No | No preference. |

Each background layer supports `image`, `method`, `slices`, `scale`, and `anchor` as defined under [Image layers](#image-layers). Its default method is `cover`. Background layers do not support decoration conditions or tinting.

Background color preferences do not recolor background artwork. Layers retain their source alpha and composite in declaration order over paper-white. A recognized package prevents its internal PNGs from being independently discovered as standalone backgrounds.

A top-level `image` field invalidates a background manifest. Required artwork belongs in the nonempty `layers` sequence.

## Decoration manifests

A decoration contains `decoration.yaml` and an ordered composition of PNG layers, with optional presentation metadata.

| Field | Type | Required | Default when omitted |
|---|---|---|---|
| `format` | Integer `1` | Yes | None. |
| `id` | Resource identifier | Yes | None. |
| `layers` | Nonempty ordered sequence of decoration-layer mappings | Yes | None. |
| `presentation_insets` | Complete four-edge inset mapping | No | Use global insets. |
| `font` | Font-bundle identifier or font-pool reference | No | No preference. |
| `font_faces` | Literary-role face preference mapping | No | No role preferences. |
| `background` | Background identifier, background-pool reference, or `"none"` | No | No preference. |
| `text_color` | Color preference | No | No preference. |
| `decoration_color` | Color preference | No | No preference. |
| `tintable` | Boolean | No | `true`. |
| `qr_ready` | Boolean | No | `true`. |
| `qr_from_left` | Nonnegative design-canvas pixel integer | No | See per-axis defaults below. |
| `qr_from_right` | Nonnegative design-canvas pixel integer | No | See per-axis defaults below. |
| `qr_from_top` | Nonnegative design-canvas pixel integer | No | See per-axis defaults below. |
| `qr_from_bottom` | Nonnegative design-canvas pixel integer | No | See per-axis defaults below. |
| `qr_centered` | `"horizontal"` or `"vertical"` | No | No centering. |

The bundled decoration identifiers are `ethereal`, `hex`, `lower-flourish`, `simple-border`, and `top-bottom-borders`.

Decorations provide artwork and the listed preferences. They cannot supply arbitrary drawing instructions, independently positioned text fields, or new literary styles.

### Presentation insets

When supplied, `presentation_insets` must contain all four fields:

| Field | Type | Required |
|---|---|---|
| `left` | Nonnegative design-canvas pixel integer | Yes. |
| `right` | Nonnegative design-canvas pixel integer | Yes. |
| `top` | Nonnegative design-canvas pixel integer | Yes. |
| `bottom` | Nonnegative design-canvas pixel integer | Yes. |

The complete mapping replaces the global `presentation.insets` mapping; edges are not merged individually. Omission uses the global mapping.

Insets are measured inward from the selected aspect-specific design canvas, independently of PNG dimensions, slices, and artwork transformations. They are pixel distances, not normalized coordinates.

| Declared aspect | Design canvas |
|---|---|
| `4:3` | 3200 × 2400 |
| `5:3` | 3840 × 2304 |
| `16:9` | 3840 × 2160 |
| `16:10` | 3840 × 2400 |

Opposing insets must leave positive width and height: `left + right < canvas width` and `top + bottom < canvas height`. Missing edges, negative values, booleans, fractional values, strings, and null are invalid. Invalid inset metadata excludes the decoration.

The literary rectangle contains the complete quotation and any source and attribution, including fields awaiting reveal. Insets do not reserve QR space or detect artwork overlap. Authors must check the resulting composition. Geometry resolution, scaling, and stable fitting follow [Architecture](../ARCHITECTURE.md#literary-presentation-geometry).

### Resource and color preferences

`font` accepts one font-bundle identifier or a reference of the form `"@POOL_NAME"` in `fonts.pools`. It does not accept a list, direct file path, or `none`.

`background` accepts one background identifier, a reference in `backgrounds.pools`, or `"none"`. It does not accept a list or direct file path.

Pool names use the shared identifier syntax. A malformed or unavailable optional font/background preference warns and is treated as absent without excluding the decoration. Syntactically valid pool references are resolved during preparation.

`text_color` and `decoration_color` in backgrounds and decorations each accept a palette identifier, a category-specific pool reference, or a nonempty sequence of either. `text_color` references `text.colors.pools`; `decoration_color` references `decorations.colors.pools`. Both use the shared palette. Direct RGB literals, RGB lists, and `none` suppression are unsupported in these preference fields.

Malformed outer values and invalid or unavailable members are diagnosed and ignored without excluding an otherwise usable asset. Valid members remain usable; duplicates do not add weight. A preference with no usable candidates expresses no effective preference. Omitted preferences express no preference.

Palette definitions and pool declarations are specified in [Application Configuration](CONFIGURATION.md#palette). Selection precedence and fallthrough are specified in [Architecture](../ARCHITECTURE.md#daily-background-and-decoration-selection), with decoration-color resolution in [Decoration tinting](../ARCHITECTURE.md#decoration-tinting).

### Tintability

Decoration-wide and per-layer `tintable` values must be YAML booleans. Both default to `true`; malformed values warn and use `true`.

Effective layer tintability is `decoration.tintable AND layer.tintable`. Tinting uses one selected decoration color for effectively tintable layers, replacing RGB while preserving source alpha. Set `tintable: false` on the decoration or individual layer when authored RGB must survive. Opaque grayscale differences do not survive RGB replacement.

There is no per-layer palette choice or separate tint-activation field. `text_color` affects literary text, not artwork. Neither color preference recolors background artwork. Runtime color selection is specified in [Architecture](../ARCHITECTURE.md#decoration-tinting).

### QR readiness and positioning

`qr_ready` must be a YAML boolean and defaults to `true`. A malformed value warns and uses `true`. A valid `false` suppresses QR for the selected decoration without warning; `true` permits QR subject to presentation policy, valid placement, and raster viability.

The positioning fields locate the complete fixed 246 × 246 design-canvas pixel QR allocation, including its quiet zone. They do not configure the payload, encoding, allocation dimensions, literary insets, or a separate QR region.

| Axis | Permitted positioning methods | Default when unspecified |
|---|---|---|
| Horizontal | `qr_from_left`, `qr_from_right`, or `qr_centered: horizontal` | `qr_from_right: 20`. |
| Vertical | `qr_from_top`, `qr_from_bottom`, or `qr_centered: vertical` | `qr_from_bottom: 20`. |

At most one method may be supplied per axis. `qr_centered` is a single scalar string, so simultaneous horizontal and vertical centering is unsupported. The other axis may use an offset or its default.

Directional offsets are nonnegative integer distances inward from the named design-canvas edges. Booleans, strings, fractional values, null, and other types are invalid. `qr_centered` accepts exactly `horizontal` or `vertical`, not a list or mapping. Per-axis defaults apply independently, including when no decoration is selected.

Malformed positioning, conflicting anchors, or an out-of-bounds complete allocation suppresses QR for that preparation with an actionable warning. The decoration remains usable. No precedence, clamping, alternate position, or position fallback is inferred.

Effective availability also requires sufficient presentation-canvas pixels. Availability is resolved before selecting conditional artwork. QR rasterization and composition, fixed encoding, rounding, and output-dependent viability are specified in [Architecture](../ARCHITECTURE.md#qr-generation-and-conditional-artwork).

## Image layers

Both packaged backgrounds and decorations use nonempty, ordered layer sequences. Each referenced source must be a readable, single-frame RGB or RGBA PNG with positive dimensions. Other image formats and modes are unsupported. RGBA transparency is preserved.

| Field | Type | Required | Default |
|---|---|---|---|
| `image` | Package-relative PNG path | Yes | None. |
| `method` | `contain`, `cover`, `nine-slice`, or `anchor` | No | Background: `cover`; decoration: `contain`. |
| `slices` | Nine-slice mapping | For `nine-slice` only | None. |
| `scale` | `horizontal`, `vertical`, or `none` | For `anchor` only | None. |
| `anchor` | Complete two-axis anchor mapping | For `anchor` only | None. |
| `condition` | `always`, `qr`, or `no-qr` | Decoration only; optional | `always`. |
| `tintable` | Boolean | Decoration only; optional | `true`. |

Values are case-sensitive. Layers composite in declaration order. All decoration artwork is behind literary text and QR; no foreground phase or arbitrary z-index is defined. [Architecture](../ARCHITECTURE.md#raster-composition-pipeline) specifies composition order and rendering.

Full-canvas artwork should use the 3840 × 2400 reference-quality authoring size. Smaller PNGs are accepted but may lose sharpness when enlarged. Source dimensions do not establish an alternate reference coordinate system.

Transformations use the design canvas. The completed graphical composition is scaled to the presentation canvas; an aspect-mismatched requested output is produced through the complete-image resize specified in [Architecture](../ARCHITECTURE.md#image-spaces-and-output-geometry).

### Contain and cover

`contain` preserves aspect ratio, scales the complete source to fit within the design canvas, and centers it. Uncovered areas reveal the underlying composition.

`cover` preserves aspect ratio, scales the source directly until it covers the design canvas, and crops excess artwork symmetrically around the center. For a 3840 × 2400 source on the 3200 × 2400 design canvas, it crops 320 pixels from each horizontal edge.

Neither method accepts `slices`, `scale`, or `anchor`.

### Anchor

`anchor` requires both `scale` and a complete `anchor` mapping, and accepts no `slices`.

| `scale` | Meaning |
|---|---|
| `horizontal` | Uniformly scale to the design-canvas width. |
| `vertical` | Uniformly scale to the design-canvas height. |
| `none` | Preserve source pixels at 1:1 size. |

| Anchor field | Accepted values | Required |
|---|---|---|
| `horizontal` | `left`, `center`, `right` | Yes. |
| `vertical` | `top`, `center`, `bottom` | Yes. |

Scaling preserves aspect ratio. Round the other dimension to the nearest pixel, with half-pixel values rounded upward. Align the complete scaled rectangle to the named canvas positions, then alpha-composite it. Artwork beyond the canvas is clipped normally without warning; oversized anchored artwork is valid.

Both anchor axes must be supplied, even if one is geometrically redundant for the selected scale. Unknown anchor fields invalidate the containing resource.

### Nine-slice

`nine-slice` requires `slices` and accepts no `scale` or `anchor`.

| Slice field | Type | Required | Default |
|---|---|---|---|
| `left` | Nonnegative source-image pixel integer | Yes | None. |
| `right` | Nonnegative source-image pixel integer | Yes | None. |
| `top` | Nonnegative source-image pixel integer | Yes | None. |
| `bottom` | Nonnegative source-image pixel integer | Yes | None. |
| `horizontal` | `stretch` or `crop` | No | `stretch`. |
| `vertical` | `stretch` or `crop` | No | `stretch`. |

Booleans, fractional values, negative measurements, and non-integer values are invalid. The left and right distances must sum to no more than the source width; top and bottom must sum to no more than its height. Source regions required by the destination must contain usable artwork.

The four distances partition the actual source into nine regions and also specify preserved edge thicknesses on the design canvas, numerically 1:1. Do not first scale the source or its slice boundaries through the reference envelope.

Corners retain their widths and heights. Horizontal edge segments adapt along their length using `slices.horizontal`; vertical edge segments use `slices.vertical`. `stretch` adapts length; `crop` retains scale and trims opposite ends symmetrically. A crop destination longer than its source segment is invalid. The center stretches in both dimensions. Edge tiling is unsupported.

The design canvas must accommodate opposing preserved edge thicknesses. Transformation viability depends on the selected canvas as well as source dimensions. Shared boundaries and rounding follow [Architecture](../ARCHITECTURE.md#decoration-layers).

### Decoration conditions

| `condition` | Included when |
|---|---|
| `always` | QR is available or unavailable. |
| `qr` | QR is effectively available. |
| `no-qr` | QR is effectively unavailable. |

Conditions preserve the relative order of remaining layers. They neither enable nor disable QR. Availability includes policy, readiness, valid placement, and sufficient presentation-canvas pixels. Invalid conditions exclude the containing decoration.

## Validation and fallback contracts

Malformed YAML, unsupported `format`, invalid identifiers, structurally invalid required data, invalid layer definitions or parameter combinations, invalid images, and invalid decoration insets exclude the affected resource without invalidating unrelated resources. Invalid optional font faces follow the font-specific recovery rule above.

Discovery validates image metadata and integrity; successful registration does not guarantee that decoding or every canvas-dependent transformation will succeed later. Invalid nine-slice source boundaries exclude the resource. Destination-dependent transformation failures are handled during preparation according to [Architecture](../ARCHITECTURE.md#background-and-decoration-recovery).

Recoverable optional metadata uses only its stated fallback: ignored preferences, ignored malformed face-preference mappings, default `true` for malformed tintability/readiness, and QR suppression for invalid placement. Invalid optional metadata must not silently gain invented values.

Warnings must identify the affected file/resource and field where applicable and explain exclusion, ignoring, or fallback. Logging and resource-validation testing requirements are specified in [Engineering](../ENGINEERING.md#resource-validation).

Resource-selection fallback, regular-face fallback, paper-white or omitted-artwork recovery, complete-image cache reuse, and canonical-selection stability follow [Architecture](../ARCHITECTURE.md#presentation-and-rendering). Registration does not require membership in a default pool. Empty pool membership is not repaired by adding fallback identifiers; pool validity is specified in [Application Configuration](CONFIGURATION.md#pool-validity-and-effective-membership). Strict viewer override behavior is specified in [CLI](../CLI.md#presentation-overrides).

## Complete examples

The following are complete manifests. Their referenced files must be supplied in the indicated package; examples do not embed binary artwork or font data. All identifiers are independent of package-directory names.

### Font bundle

Place this `font.yaml` beside usable `Lora-Regular.ttf` and `Lora-Italic.ttf` files, retaining their applicable license:

```yaml
format: 1
id: literary
faces:
  regular: Lora-Regular.ttf
  italic: Lora-Italic.ttf
font_faces:
  quotation: regular
  source: italic
  attribution: italic
```

### Standalone background

Place a single-frame RGB or RGBA PNG at `assets/backgrounds/paper.png`. It registers `paper`, uses centered cover, and needs no manifest.

### Layered background

Place this `background.yaml` with `paper.png` (RGB, 3840 × 2400), `vignette.png` (RGBA, 3840 × 2400), and `corner.png` (RGBA, 240 × 240):

```yaml
format: 1
id: layered-paper
text_color: black
decoration_color: [black, blue]
layers:
  - image: paper.png
    method: cover
  - image: vignette.png
    method: nine-slice
    slices:
      left: 96
      right: 96
      top: 96
      bottom: 96
      horizontal: stretch
      vertical: stretch
  - image: corner.png
    method: anchor
    scale: none
    anchor:
      horizontal: right
      vertical: top
```

### Decoration with conditional layers

Place this `decoration.yaml` with `border.png` (RGBA, 3840 × 2400), `accent.png` (RGBA, 240 × 240), and `qr-corner.png` and `closed-corner.png` (RGBA, 300 × 300). The example prefers bundled `lora` and the `layered-paper` background above:

```yaml
format: 1
id: literary-border
presentation_insets:
  left: 384
  right: 384
  top: 324
  bottom: 324
font: lora
font_faces:
  quotation: regular
  source: italic
  attribution: italic
background: layered-paper
text_color: black
decoration_color: [black, blue]
tintable: true
qr_ready: true
qr_from_right: 20
qr_from_bottom: 20
layers:
  - image: border.png
    method: nine-slice
    slices:
      left: 96
      right: 96
      top: 96
      bottom: 96
      horizontal: stretch
      vertical: stretch
    condition: always
  - image: accent.png
    method: anchor
    scale: none
    anchor:
      horizontal: left
      vertical: top
    tintable: false
  - image: qr-corner.png
    method: anchor
    scale: none
    anchor:
      horizontal: right
      vertical: bottom
    condition: qr
  - image: closed-corner.png
    method: anchor
    scale: none
    anchor:
      horizontal: right
      vertical: bottom
    condition: no-qr
```

### Centered QR and crop edges

Place this complete `decoration.yaml` with an RGBA `wide-border.png` at 4000 × 2600. Its source edge segments are long enough for centered cropping on every supported design canvas:

```yaml
format: 1
id: centered-border
qr_centered: horizontal
qr_from_bottom: 20
layers:
  - image: wide-border.png
    method: nine-slice
    slices:
      left: 100
      right: 100
      top: 100
      bottom: 100
      horizontal: crop
      vertical: crop
```

