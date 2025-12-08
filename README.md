# FARM_Time-

## Bugonia coat pattern helper

To extract a coat pattern summary for Bugonia from her photos, install the
Python requirement and run the helper script:

```bash
pip install -r requirements.txt
python coat_pattern.py --dir sheep_ids/input/Bugonia
```

Place Bugonia's photos under `sheep_ids/input/Bugonia/` (JPG/PNG/TIF are
supported). The script aggregates an adaptive color palette across all images
and reports whether her coat looks solid, two-tone, or multi-tone. Example
output:

```
Analyzed 8 photo(s) from /abs/path/to/sheep_ids/input/Bugonia

Dominant colors:
  - 52.0% tan (rgb=198,155,115)
  - 28.0% brown (rgb=114,73,44)
  - 12.0% cream (rgb=231,219,192)

Pattern inference:
  Two-tone coat with a visible secondary color.
```

## Sheep re-identification helper

To automatically crop and group the same sheep across many photos, install the
Python requirements and run the identifier:

```bash
pip install -r requirements.txt
python sheep_identifier.py --dir sheep_ids/input --output sheep_ids/output
```

This performs the following steps for every image in the input directory tree:

1. Detects sheep using a pre-trained Faster R-CNN model.
2. Crops each detection and extracts its coat palette as a compact feature.
3. Groups detections that share similar coat features into per-sheep folders
   (e.g., `sheep_001/`, `sheep_002/`).

Crops and a `manifest.json` describing the matches are written under the output
directory.
