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
