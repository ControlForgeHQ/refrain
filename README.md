# Refrain

**Made for a quieter kind of noticing.**

Refrain is an open-source application that presents quotations, lyrics, and other meaningful passages on a digital display.

Rather than demanding attention, Refrain is designed to reward it. A quotation is selected each day, with its contents and attribution progressively revealed over time.

The project began as a personal e-paper display, but is being developed to support different display technologies, resolutions, and visual presentations.

## Project status

**Refrain is under active development.**

The application is functional, but its presentation system, configuration, deployment experience, and documentation are still evolving. It is not yet intended as a polished, general-purpose release.

Development progress, planned features, and outstanding work are tracked through the repository's [Issues](https://github.com/ControlForgeHQ/refrain/issues) and [Pull Requests](https://github.com/ControlForgeHQ/refrain/pulls).

For intended features and release milestones, see the [Roadmap](docs/ROADMAP.md).

More information will follow as Refrain approaches its first release.

## Filesystem publication

Refrain can publish the current scheduled presentation into a destination-owned
directory that remains available after the resident exits:

```yaml
storage:
  publish: /srv/refrain/publications

destinations:
  - id: web-public
    type: publish
    audience: public
    aspect_ratio: "16:10"
    resolution: [3840, 2400]
```

Inspect the committed presentation without the resident or its content library:

```sh
refrain-viewer --publication /srv/refrain/publications/web-public/<publication-id>.json
```

The viewer reads the metadata file referenced by the destination's
`manifest.json`; see [Content Format](docs/CONTENT_FORMAT.md#display-destinations)
and [Architecture](docs/ARCHITECTURE.md#filesystem-publication-target-backend-integration-implemented)
for configuration and publication behavior.

---

Created by Edward Wright.

Licensed under the [MIT License](LICENSE).
