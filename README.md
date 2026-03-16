# FARM_Time-

## Sheep ID tool quickstart
This repo includes `sheep_ids/sheep_ids.py`, which detects sheep in images/videos, saves crops, and can snapshot a single image with numbered labels.

### Setup (CPU)
```bash
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install --upgrade pip
# Install lightweight CPU wheels for torch first (avoids 900MB+ CUDA download):
pip install torch==2.3.1 torchvision==0.18.1 --index-url https://download.pytorch.org/whl/cpu
pip install -r sheep_ids/requirements.txt --upgrade-strategy only-if-needed
```

### Running the snapshot labeler
```bash
python sheep_ids/sheep_ids.py --snapshot sheep_ids/input/IMG_0324.JPEG
```
- Writes annotated image to `output/sheep_snapshot.jpg` and boxes CSV to `output/sheep_snapshot.csv` (paths are relative to your current working directory).
- Latest run (Dec 4) labeled 12 sheep in `IMG_0324.JPEG` using the default YOLOv8n + CLIP face filter; see `output/sheep_snapshot.jpg` and `output/sheep_snapshot.csv` for review.

### Full pipeline (frames → crops → clusters)
Run without `--snapshot` to process everything under `sheep_ids/input`:
```bash
python sheep_ids/sheep_ids.py
```
Outputs go to `sheep_ids/work/` (frames, crops) and `sheep_ids/output/` (representative cluster images + `sheep_index.csv`). Adjust constants near the top of the script (e.g., `FRAME_STRIDE`, `DBSCAN_EPS`) if you need different sampling or clustering sensitivity.

## Scheduled retrain workflow
- GitHub Actions workflow at `.github/workflows/retrain.yml` runs weekly (Mon 03:00 UTC) or on manual dispatch.
- Steps: checkout, set up Python 3.10, `pip install -r requirements.txt`, run `train.py` with `--data data/ --config configs/exp.yaml --out outputs/latest`, then `eval.py` compares metrics to `metrics/prod.json` and uploads `outputs/latest` as artifacts.
- Replace the placeholder training/eval logic with your real model code and metrics; add your dependencies to `requirements.txt`.

## Local usage (stubs)
- Install deps: `pip install -r requirements.txt`
- Train stub: `python train.py --data data/ --config configs/exp.yaml --out outputs/latest`
- Eval stub: `python eval.py --model outputs/latest/model.pt --metrics outputs/latest/metrics.json --baseline metrics/prod.json`

## New files
- `.github/workflows/retrain.yml`: scheduled/dispatchable retrain + eval + artifact upload.
- `train.py`: stub training script that writes placeholder model + metrics.
- `eval.py`: stub evaluation that fails on regressions vs. `metrics/prod.json`.
- `configs/exp.yaml`: placeholder experiment config.
- `requirements.txt`: add your actual dependencies here.
