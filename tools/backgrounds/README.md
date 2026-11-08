# Refrain background collection

| Filename | Surface |
| --- | --- |
| `aged-paper.png` | Honey-buff stock with pressed grain and gentle warmth near the edges. |
| `canvas.png` | Light canvas with rounded over-under yarns and small variations in yarn spacing. |
| `cloth.png` | Warm linen with narrow, irregular threads and a visible crossweave. |
| `hex.png` | Fine graphite honeycomb ruling on an off-white ground. |
| `handmade-paper.png` | Pale cotton rag with curved pulp fibres in varied lengths and tones. |
| `vellum.png` | Matte ivory with close stippling and small embossed wrinkles. |
| `limestone.png` | Cool, light stone with mineral flecks and small pores. |
| `drafting-grid.png` | Pale blue square ruling with a stronger guide at every fifth line. |
| `isometric-grid.png` | Three evenly spaced line families meeting at 60° on pale lilac. |
| `recursive-squares.png` | A pale sage repeating field of square outlines at two scales, based on two steps of Sierpiński carpet subdivision. |

## Origin and redistribution

All ten masters were generated directly on the 3840 × 2400 grid with NumPy and Pillow.  No bundled-image pixels or third-party textures are included in the masters.

The artwork is intended for redistribution under [Refrain’s MIT License](https://github.com/ControlForgeHQ/refrain/blob/main/LICENSE) to the extent that applicable intellectual-property rights exist. Generation and preview sources are in `source/`.

## Regenerate the masters

`generate.py` creates all ten PNGs from scratch using Python, NumPy, and Pillow. Each design has a fixed seed. The script requires no source images or files.

```sh
python source/generate.py --output-dir regenerated
```

Omit `--output-dir` to write to `backgrounds/` in the current directory. The regenerated files matched the accepted masters byte for byte with Python 3.12.14, NumPy 2.3.5, and Pillow 13.0.0.