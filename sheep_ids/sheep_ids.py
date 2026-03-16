from __future__ import annotations

import sys
import math
import csv
import argparse
from pathlib import Path
from typing import List, Tuple, Dict, Optional

import cv2
import numpy as np
from PIL import Image
from ultralytics import YOLO
from sentence_transformers import SentenceTransformer
from sklearn.cluster import DBSCAN


# ----------------------------
# Constants / Configuration
# ----------------------------
INPUT_DIR = Path("input")
WORK_DIR = Path("work")
FRAMES_DIR = WORK_DIR / "frames"
CROPS_DIR = WORK_DIR / "crops"
OUTPUT_DIR = Path("output")

VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

FRAME_STRIDE = 10        # take 1 frame every N frames from each video
DETECTION_CONF = 0.4     # minimum confidence for YOLO detections
SHEEP_CLASS_ID = 18      # COCO class index for sheep (0-based; 18 == sheep)

DBSCAN_EPS = 0.35        # clustering radius, cosine space
DBSCAN_MIN_SAMPLES = 3   # minimum samples to form a cluster

# Snapshot-specific tuning
SNAPSHOT_DET_CONF = 0.25     # slightly lower conf to catch more candidates
SNAPSHOT_PAD_RATIO = 0.05    # padding around bbox for crops
SNAPSHOT_UPPER_RATIO = 0.7   # keep upper part biasing toward face
SNAPSHOT_FACE_MARGIN = 0.00  # CLIP face-vs-rear margin threshold
SNAPSHOT_TARGET_COUNT = 12   # aim to keep around this many faces if available
SNAPSHOT_HEAD_BOX_HEIGHT_RATIO = 0.45  # head box height as fraction of head region
SNAPSHOT_HEAD_BOX_WIDTH_RATIO  = 0.50  # head box width as fraction of head region
SNAPSHOT_CENTER_STEPS = 7              # candidate horizontal centers across head
SNAPSHOT_EYE_Y_FRACTION = 0.22         # vertical start within head to target eyes


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS


def _ensure_dirs() -> None:
    WORK_DIR.mkdir(exist_ok=True)
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)
    CROPS_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)


def extract_frames() -> int:
    """Extract frames from videos and copy still images into work/frames as JPGs.

    Returns the number of frame images written.
    """
    FRAMES_DIR.mkdir(parents=True, exist_ok=True)

    if not INPUT_DIR.exists():
        print(f"ERROR: Missing input folder: {INPUT_DIR}")
        return 0

    input_files = sorted([p for p in INPUT_DIR.iterdir() if p.is_file() and (_is_video(p) or _is_image(p))])
    print(f"Found {len(input_files)} input files in {INPUT_DIR}.")

    written = 0
    for src in input_files:
        stem = src.stem
        if _is_video(src):
            cap = cv2.VideoCapture(str(src))
            if not cap.isOpened():
                print(f"Warning: Could not open video: {src}")
                continue

            idx = 0
            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                if idx % FRAME_STRIDE == 0:
                    # convert to RGB for consistency before writing as JPG
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    out_name = f"{stem}_f{frame_idx:06d}.jpg"
                    out_path = FRAMES_DIR / out_name
                    cv2.imwrite(str(out_path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
                    written += 1
                    frame_idx += 1
                idx += 1
            cap.release()
        elif _is_image(src):
            # Read and re-encode as JPG into frames directory
            img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
            if img is None:
                print(f"Warning: Could not read image: {src}")
                continue
            # Handle alpha by compositing onto white background
            if img.shape[-1] == 4:
                bgr = img[:, :, :3]
                alpha = img[:, :, 3] / 255.0
                white = np.ones_like(bgr, dtype=np.uint8) * 255
                bgr = (bgr * alpha[..., None] + white * (1 - alpha[..., None])).astype(np.uint8)
            else:
                bgr = img
            out_name = f"{stem}_f000000.jpg"
            out_path = FRAMES_DIR / out_name
            cv2.imwrite(str(out_path), bgr)
            written += 1

    print(f"Frames written: {written} -> {FRAMES_DIR}")
    return written


def detect_and_crop() -> int:
    """Run YOLO detection on frames and save upper-body crops of detected sheep.

    Returns number of crops saved.
    """
    CROPS_DIR.mkdir(parents=True, exist_ok=True)

    frame_paths = sorted([p for p in FRAMES_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS or p.suffix.lower() == ".jpg"])
    if not frame_paths:
        print(f"No frames found in {FRAMES_DIR}. Did you run extract_frames()?")
        return 0

    print("Loading YOLOv8 model (yolov8n.pt)...")
    try:
        model = YOLO("yolov8n.pt")  # downloads on first use
    except Exception as e:
        print(f"ERROR loading YOLO model: {e}")
        return 0

    crop_count = 0
    pad_ratio = 0.05  # 5% padding around bbox
    upper_ratio = 0.7  # keep upper 70% of height

    for i, fpath in enumerate(frame_paths, 1):
        try:
            pil = Image.open(fpath).convert("RGB")
        except Exception as e:
            print(f"Warning: Skipping unreadable frame {fpath}: {e}")
            continue

        img_np = np.array(pil)  # RGB
        try:
            results = model.predict(img_np, conf=DETECTION_CONF, verbose=False)
        except Exception as e:
            print(f"Warning: YOLO inference failed on {fpath}: {e}")
            continue

        if not results:
            continue

        r = results[0]
        if r.boxes is None or len(r.boxes) == 0:
            continue

        boxes_xyxy = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        clses = r.boxes.cls.cpu().numpy().astype(int)

        W, H = pil.size
        for (x1, y1, x2, y2), conf, cls in zip(boxes_xyxy, confs, clses):
            if cls != SHEEP_CLASS_ID or conf < DETECTION_CONF:
                continue

            bw = x2 - x1
            bh = y2 - y1
            if bw <= 1 or bh <= 1:
                continue

            pw = int(bw * pad_ratio)
            ph = int(bh * pad_ratio)
            px1 = max(0, int(math.floor(x1 - pw)))
            py1 = max(0, int(math.floor(y1 - ph)))
            px2 = min(W, int(math.ceil(x2 + pw)))
            py2 = min(H, int(math.ceil(y2 + ph)))

            # Crop padded bbox
            crop = pil.crop((px1, py1, px2, py2))
            cw, ch = crop.size
            if cw < 5 or ch < 5:
                continue

            # Keep upper ~70% to bias towards head/upper body
            upper_h = max(1, int(ch * upper_ratio))
            head_crop = crop.crop((0, 0, cw, upper_h))

            crop_count += 1
            out_name = f"crop_{crop_count:05d}.jpg"
            out_path = CROPS_DIR / out_name
            try:
                head_crop.save(out_path, format="JPEG", quality=95)
            except Exception as e:
                print(f"Warning: Failed saving crop {out_path}: {e}")
                crop_count -= 1

        if i % 100 == 0:
            print(f"Processed {i} frames...")

    print(f"Crops saved: {crop_count} -> {CROPS_DIR}")
    return crop_count


def _load_crops() -> List[Path]:
    return sorted([p for p in CROPS_DIR.iterdir() if p.suffix.lower() in IMAGE_EXTS or p.suffix.lower() == ".jpg"])


def _image_area(path: Path) -> int:
    try:
        with Image.open(path) as im:
            w, h = im.size
        return w * h
    except Exception:
        return -1


def cluster_and_export() -> Tuple[int, Dict[int, Path]]:
    """Cluster crop embeddings and export one representative per cluster.

    Returns (num_clusters, mapping cluster_label -> chosen_image_path).
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    crop_paths = _load_crops()
    if not crop_paths:
        print(f"No crops found in {CROPS_DIR}. Skipping clustering.")
        return 0, {}

    print(f"Embedding {len(crop_paths)} crops with CLIP (clip-ViT-B-32)...")
    try:
        model = SentenceTransformer("clip-ViT-B-32")
    except Exception as e:
        print(f"ERROR loading embedding model: {e}")
        return 0, {}

    # Load images as PIL for the image-capable ST models
    images: List[Image.Image] = []
    for p in crop_paths:
        try:
            images.append(Image.open(p).convert("RGB"))
        except Exception as e:
            print(f"Warning: Skipping unreadable crop {p}: {e}")
            images.append(None)  # placeholder to keep indices aligned

    valid_indices = [i for i, im in enumerate(images) if im is not None]
    valid_images = [images[i] for i in valid_indices]
    valid_paths = [crop_paths[i] for i in valid_indices]

    if not valid_images:
        print("No valid crops to embed.")
        return 0, {}

    try:
        embeddings = model.encode(
            valid_images,
            batch_size=32,
            convert_to_numpy=True,
            show_progress_bar=True,
        )
    except Exception as e:
        print(f"ERROR during embedding: {e}")
        return 0, {}

    # Normalize embeddings for stable cosine distances
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-12
    embeddings = embeddings / norms

    print("Clustering with DBSCAN (cosine metric)...")
    try:
        db = DBSCAN(metric="cosine", eps=DBSCAN_EPS, min_samples=DBSCAN_MIN_SAMPLES)
        labels = db.fit_predict(embeddings)
    except Exception as e:
        print(f"ERROR during clustering: {e}")
        return 0, {}

    label_set = sorted([lbl for lbl in set(labels.tolist()) if lbl != -1])
    num_clusters = len(label_set)
    print(f"Clusters found (excluding noise): {num_clusters}")

    if num_clusters == 0:
        print("No clusters were formed. Try adjusting DBSCAN_EPS or DBSCAN_MIN_SAMPLES.")
        return 0, {}

    # Group paths by cluster label
    clusters: Dict[int, List[Path]] = {lbl: [] for lbl in label_set}
    for idx, lbl in zip(range(len(valid_paths)), labels):
        if lbl == -1:
            continue
        clusters[lbl].append(valid_paths[idx])

    # Choose best crop by largest area
    chosen: Dict[int, Path] = {}
    for lbl in label_set:
        members = clusters[lbl]
        if not members:
            continue
        best = max(members, key=_image_area)
        chosen[lbl] = best

    # Export chosen images and CSV index
    csv_path = OUTPUT_DIR / "sheep_index.csv"
    rows: List[Tuple[str, int, str]] = []

    # Sort by cluster label for stable Sheep_XX numbering
    for idx, lbl in enumerate(label_set, 1):
        src = chosen.get(lbl)
        if src is None:
            continue
        sheep_id = f"Sheep_{idx:02d}"
        out_img = OUTPUT_DIR / f"{sheep_id}.jpg"
        try:
            # Copy image contents to output
            with Image.open(src).convert("RGB") as im:
                im.save(out_img, format="JPEG", quality=95)
        except Exception as e:
            print(f"Warning: Failed saving representative image for cluster {lbl}: {e}")
            continue
        rows.append((sheep_id, lbl, src.name))

    # Write CSV
    try:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["sheep_id", "cluster_label", "source_crop"])  # header
            for sheep_id, lbl, src_name in rows:
                writer.writerow([sheep_id, lbl, src_name])
    except Exception as e:
        print(f"Warning: Failed to write CSV index: {e}")

    print(f"Wrote {len(rows)} representative images -> {OUTPUT_DIR}")
    print(f"CSV index: {csv_path}")

    return num_clusters, {lbl: chosen[lbl] for lbl in chosen}


def annotate_single_image(image_path: Optional[Path] = None, max_auto_try: int = 30) -> Tuple[int, Optional[Path]]:
    """Annotate one image with numbered sheep detections and save snapshot + CSV.

    If image_path is None, auto-select from INPUT_DIR by scanning up to max_auto_try
    images and choosing the one with the most sheep detected.

    Returns (num_sheep, chosen_image_path).
    """
    OUTPUT_DIR.mkdir(exist_ok=True)

    print("Loading YOLOv8 model (yolov8n.pt) for snapshot...")
    try:
        model = YOLO("yolov8n.pt")
    except Exception as e:
        print(f"ERROR loading YOLO model: {e}")
        return 0, None

    chosen_path: Optional[Path] = None
    if image_path is None:
        if not INPUT_DIR.exists():
            print(f"ERROR: '{INPUT_DIR}' does not exist.")
            return 0, None
        candidates = [p for p in INPUT_DIR.iterdir() if p.is_file() and _is_image(p)]
        if not candidates:
            print(f"No images in {INPUT_DIR} to snapshot.")
            return 0, None
        # Try at most max_auto_try candidates, sorted by size (largest first)
        try:
            candidates.sort(key=lambda p: p.stat().st_size, reverse=True)
        except Exception:
            candidates.sort()
        candidates = candidates[:max_auto_try]

        best_count = -1
        best_path = None
        for p in candidates:
            try:
                img_bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
                if img_bgr is None:
                    continue
                img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
                res = model.predict(img_rgb, conf=SNAPSHOT_DET_CONF, verbose=False)
                if not res:
                    continue
                r = res[0]
                if r.boxes is None or len(r.boxes) == 0:
                    count = 0
                else:
                    clses = r.boxes.cls.cpu().numpy().astype(int)
                    confs = r.boxes.conf.cpu().numpy()
                    count = int(((clses == SHEEP_CLASS_ID) & (confs >= DETECTION_CONF)).sum())
                if count > best_count:
                    best_count = count
                    best_path = p
            except Exception:
                continue
        chosen_path = best_path if best_path is not None else candidates[0]
        if best_count <= 0:
            print("Warning: No sheep detected in auto-selection; using the first image anyway.")
    else:
        chosen_path = image_path

    if chosen_path is None:
        print("No image chosen for snapshot.")
        return 0, None

    # Load chosen image
    img_bgr = cv2.imread(str(chosen_path), cv2.IMREAD_COLOR)
    if img_bgr is None:
        print(f"ERROR: Could not read image: {chosen_path}")
        return 0, chosen_path
    H, W = img_bgr.shape[:2]

    # Run inference
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    try:
        results = model.predict(img_rgb, conf=SNAPSHOT_DET_CONF, verbose=False)
    except Exception as e:
        print(f"ERROR: YOLO inference failed on {chosen_path}: {e}")
        return 0, chosen_path

    if not results or results[0].boxes is None or len(results[0].boxes) == 0:
        print("No detections found.")
        # Save the original as snapshot anyway
        out_img = OUTPUT_DIR / "sheep_snapshot.jpg"
        cv2.imwrite(str(out_img), img_bgr)
        # Empty CSV
        out_csv = OUTPUT_DIR / "sheep_snapshot.csv"
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["sheep_id", "confidence", "x1", "y1", "x2", "y2", "source_image"])  # header
        print(f"Snapshot saved (no sheep detected): {out_img}")
        return 0, chosen_path

    r = results[0]
    boxes_xyxy = r.boxes.xyxy.cpu().numpy()
    confs = r.boxes.conf.cpu().numpy()
    clses = r.boxes.cls.cpu().numpy().astype(int)

    # Filter sheep detections
    dets = []  # (x1, y1, x2, y2, conf)
    for (x1, y1, x2, y2), conf, cls in zip(boxes_xyxy, confs, clses):
        if cls == SHEEP_CLASS_ID and conf >= SNAPSHOT_DET_CONF:
            dets.append((float(x1), float(y1), float(x2), float(y2), float(conf)))

    if not dets:
        out_img = OUTPUT_DIR / "sheep_snapshot.jpg"
        cv2.imwrite(str(out_img), img_bgr)
        out_csv = OUTPUT_DIR / "sheep_snapshot.csv"
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["sheep_id", "confidence", "x1", "y1", "x2", "y2", "source_image"])  # header
        print(f"Snapshot saved (no sheep detected): {out_img}")
        return 0, chosen_path

    # Build head/upper-body crops for CLIP filtering
    pil_full = Image.fromarray(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB))
    head_crops: List[Image.Image] = []
    # kept_meta stores for each detection:
    # (x1, y1, x2, y2, conf, head_origin_x, head_origin_y, head_w, head_h)
    kept_meta: List[Tuple[float, float, float, float, float, int, int, int, int]] = []
    for (x1, y1, x2, y2, conf) in dets:
        bw = x2 - x1
        bh = y2 - y1
        if bw <= 1 or bh <= 1:
            continue
        pw = int(bw * SNAPSHOT_PAD_RATIO)
        ph = int(bh * SNAPSHOT_PAD_RATIO)
        px1 = max(0, int(math.floor(x1 - pw)))
        py1 = max(0, int(math.floor(y1 - ph)))
        px2 = min(W, int(math.ceil(x2 + pw)))
        py2 = min(H, int(math.ceil(y2 + ph)))
        crop = pil_full.crop((px1, py1, px2, py2))
        cw, ch = crop.size
        if cw < 5 or ch < 5:
            continue
        upper_h = max(1, int(ch * SNAPSHOT_UPPER_RATIO))
        head = crop.crop((0, 0, cw, upper_h))
        head_crops.append(head)
        kept_meta.append((x1, y1, x2, y2, conf, px1, py1, cw, upper_h))

    if not head_crops:
        # Fallback: draw all detections
        sheep = dets
        sheep.sort(key=lambda b: b[0])
        thickness = max(2, int(round(min(H, W) / 300)))
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = max(0.5, min(H, W) / 1000)
        for idx, (x1, y1, x2, y2, conf) in enumerate(sheep, 1):
            p1 = (int(round(x1)), int(round(y1)))
            p2 = (int(round(x2)), int(round(y2)))
            color = (0, 200, 255)
            cv2.rectangle(img_bgr, p1, p2, color, thickness)
            label = f"Sheep_{idx:02d}"
            (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
            bx1, by1 = p1[0], max(0, p1[1] - th - baseline - 4)
            bx2, by2 = bx1 + tw + 6, p1[1]
            cv2.rectangle(img_bgr, (bx1, by1), (bx2, by2), color, -1)
            cv2.putText(img_bgr, label, (bx1 + 3, by2 - 3), font, font_scale, (0, 0, 0), 1, cv2.LINE_AA)
        out_img = OUTPUT_DIR / "sheep_snapshot.jpg"
        cv2.imwrite(str(out_img), img_bgr)
        out_csv = OUTPUT_DIR / "sheep_snapshot.csv"
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["sheep_id", "confidence", "x1", "y1", "x2", "y2", "source_image"])  # header
            for idx, (x1, y1, x2, y2, conf) in enumerate(sheep, 1):
                writer.writerow([f"Sheep_{idx:02d}", f"{conf:.3f}", int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)), chosen_path.name])
        print(f"Snapshot saved: {out_img}")
        print(f"Boxes CSV: {out_csv}")
        return len(sheep), chosen_path

    # CLIP filtering face vs rear
    try:
        clip = SentenceTransformer("clip-ViT-B-32")
        img_emb = clip.encode(head_crops, batch_size=32, convert_to_numpy=True, show_progress_bar=False)
        img_emb = img_emb / (np.linalg.norm(img_emb, axis=1, keepdims=True) + 1e-12)
        face_texts = [
            "a photo of a sheep face",
            "a photo of a sheep head",
            "front view of a sheep",
            "a sheep looking at the camera",
            "sheep muzzle",
            "sheep face closeup",
            "front of a sheep",
        ]
        rear_texts = [
            "a photo of a sheep rear end",
            "back of a sheep",
            "rear view of a sheep",
            "sheep hindquarters",
            "sheep rump",
            "sheep backside",
            "a sheep walking away",
        ]
        face_emb = clip.encode(face_texts, convert_to_numpy=True)
        rear_emb = clip.encode(rear_texts, convert_to_numpy=True)
        face_emb = face_emb / (np.linalg.norm(face_emb, axis=1, keepdims=True) + 1e-12)
        rear_emb = rear_emb / (np.linalg.norm(rear_emb, axis=1, keepdims=True) + 1e-12)

        f_sim = img_emb @ face_emb.T
        r_sim = img_emb @ rear_emb.T
        f_max = f_sim.max(axis=1)
        r_max = r_sim.max(axis=1)
        margin = f_max - r_max

        # Centering refinement: find best between-the-eyes center per head crop using sliding window patches
        # Prepare candidate patches across width for each head crop
        center_patches: List[Image.Image] = []
        patch_map: List[Tuple[int, int, int, int]] = []  # (det_idx, sx1, sy1, sw)
        for i, head in enumerate(head_crops):
            w, h = head.size
            sw = max(8, int(round(w * SNAPSHOT_HEAD_BOX_WIDTH_RATIO)))
            sh = max(8, int(round(h * SNAPSHOT_HEAD_BOX_HEIGHT_RATIO)))
            # candidate centers from sw/2 to w - sw/2
            if w - sw <= 0:
                cx_list = [w // 2]
            else:
                left = sw // 2
                right = w - (sw - sw // 2)
                cx_list = np.linspace(left, right, num=SNAPSHOT_CENTER_STEPS)
                cx_list = [int(round(x)) for x in cx_list]
            sy1 = int(round(SNAPSHOT_EYE_Y_FRACTION * h))
            if sy1 + sh > h:
                sy1 = max(0, h - sh)
            for cx in cx_list:
                sx1 = int(round(cx - sw / 2.0))
                sx2 = sx1 + sw
                if sx1 < 0:
                    sx1, sx2 = 0, sw
                if sx2 > w:
                    sx2, sx1 = w, w - sw
                patch = head.crop((sx1, sy1, sx2, sy1 + sh))
                center_patches.append(patch)
                patch_map.append((i, sx1, sy1, sw))

        # Encode patches and score vs face texts
        patch_scores = None
        if center_patches:
            p_emb = clip.encode(center_patches, batch_size=64, convert_to_numpy=True, show_progress_bar=False)
            p_emb = p_emb / (np.linalg.norm(p_emb, axis=1, keepdims=True) + 1e-12)
            p_sim = p_emb @ face_emb.T
            patch_scores = p_sim.max(axis=1)
        # Choose best patch per detection
        best_patch_by_det: Dict[int, Tuple[int, int, int]] = {}
        if patch_scores is not None:
            for idx_patch, score in enumerate(patch_scores):
                det_idx, sx1, sy1, sw = patch_map[idx_patch]
                cur = best_patch_by_det.get(det_idx)
                if cur is None or score > cur[0]:
                    best_patch_by_det[det_idx] = (float(score), sx1, sy1)

        # Prefer candidates where face >= rear, then apply margin threshold.
        order = sorted(range(len(margin)), key=lambda i: margin[i], reverse=True)
        base_candidates = [i for i in order if f_max[i] >= r_max[i]]
        keep_thresh = [i for i in base_candidates if margin[i] >= SNAPSHOT_FACE_MARGIN]
        target_n = min(SNAPSHOT_TARGET_COUNT, len(head_crops))
        if len(keep_thresh) >= target_n:
            kept_indices = keep_thresh[:target_n]
        elif len(base_candidates) > 0:
            kept_indices = base_candidates[:target_n]
        else:
            kept_indices = order[:target_n]
        print(f"Snapshot face filter: kept {len(kept_indices)} of {len(head_crops)} (target {SNAPSHOT_TARGET_COUNT}, margin>={SNAPSHOT_FACE_MARGIN}).")
    except Exception as e:
        print(f"Warning: CLIP filtering failed ({e}); using all detections.")
        kept_indices = list(range(len(head_crops)))

    # Build final list of boxes using refined centers where available; fallback to simple shrink
    final: List[Tuple[int, int, int, int, float]] = []
    for det_idx, meta in enumerate(kept_meta):
        x1, y1, x2, y2, conf, hx, hy, hw, hh = meta
        W_img, H_img = W, H
        # Default: simple shrink at bbox center
        bw = max(1.0, x2 - x1)
        bh = max(1.0, y2 - y1)
        def_sh = max(8, int(round(hh * SNAPSHOT_HEAD_BOX_HEIGHT_RATIO)))  # use head region height
        def_sw = max(8, int(round(hw * SNAPSHOT_HEAD_BOX_WIDTH_RATIO)))
        def_cx = hx + hw / 2.0
        def_sx1 = int(round(def_cx - def_sw / 2.0))
        def_sy1 = int(round(hy + SNAPSHOT_EYE_Y_FRACTION * hh))
        # Clamp defaults
        def_sx1 = max(0, min(def_sx1, W_img - def_sw))
        def_sy1 = max(0, min(def_sy1, H_img - def_sh))
        rx1, ry1 = def_sx1, def_sy1
        rx2, ry2 = rx1 + def_sw, ry1 + def_sh

        # If we have best patch center for this detection, use it
        # Note: best_patch_by_det is defined in the CLIP try block; if unavailable, we fall back.
        try:
            b = best_patch_by_det.get(det_idx)  # type: ignore[name-defined]
        except Exception:
            b = None
        if b is not None:
            _, sx1, sy1 = b
            rx1 = int(hx + sx1)
            ry1 = int(hy + sy1)
            rx2 = int(rx1 + def_sw)
            ry2 = int(ry1 + def_sh)

        # Clamp to image
        rx1 = max(0, min(rx1, W_img - 1))
        ry1 = max(0, min(ry1, H_img - 1))
        rx2 = max(rx1 + 1, min(rx2, W_img))
        ry2 = max(ry1 + 1, min(ry2, H_img))

        final.append((rx1, ry1, rx2, ry2, conf))

    # Sort left-to-right and draw
    final.sort(key=lambda b: b[0])
    thickness = max(2, int(round(min(H, W) / 300)))
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = max(0.5, min(H, W) / 1000)
    for idx, (x1, y1, x2, y2, conf) in enumerate(final, 1):
        # Shrink to a head-only box: top fraction of height, centered narrower width
        w = max(1.0, x2 - x1)
        h = max(1.0, y2 - y1)
        head_h = max(8, int(round(h * SNAPSHOT_HEAD_BOX_HEIGHT_RATIO)))
        head_w = max(8, int(round(w * SNAPSHOT_HEAD_BOX_WIDTH_RATIO)))
        cx = (x1 + x2) / 2.0
        nx1 = int(round(cx - head_w / 2.0))
        nx2 = int(round(cx + head_w / 2.0))
        ny1 = int(round(y1))
        ny2 = int(round(y1 + head_h))
        # Clamp to image bounds
        nx1 = max(0, min(nx1, W - 1))
        nx2 = max(0, min(nx2, W))
        ny1 = max(0, min(ny1, H - 1))
        ny2 = max(0, min(ny2, H))

        p1 = (nx1, ny1)
        p2 = (nx2, ny2)
        color = (0, 200, 255)
        cv2.rectangle(img_bgr, p1, p2, color, thickness)
        label = f"Sheep_{idx:02d}"
        (tw, th), baseline = cv2.getTextSize(label, font, font_scale, thickness)
        bx1, by1 = p1[0], max(0, p1[1] - th - baseline - 4)
        bx2, by2 = bx1 + tw + 6, p1[1]
        cv2.rectangle(img_bgr, (bx1, by1), (bx2, by2), color, -1)
        cv2.putText(img_bgr, label, (bx1 + 3, by2 - 3), font, font_scale, (0, 0, 0), 1, cv2.LINE_AA)

    out_img = OUTPUT_DIR / "sheep_snapshot.jpg"
    cv2.imwrite(str(out_img), img_bgr)
    out_csv = OUTPUT_DIR / "sheep_snapshot.csv"
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sheep_id", "confidence", "x1", "y1", "x2", "y2", "source_image"])  # header
        for idx, (x1, y1, x2, y2, conf) in enumerate(final, 1):
            writer.writerow([f"Sheep_{idx:02d}", f"{conf:.3f}", int(round(x1)), int(round(y1)), int(round(x2)), int(round(y2)), chosen_path.name])

    print(f"Snapshot saved: {out_img}")
    print(f"Boxes CSV: {out_csv}")
    return len(final), chosen_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Sheep detection and clustering utilities")
    parser.add_argument(
        "--snapshot",
        nargs="?",
        const="auto",
        default=None,
        help=(
            "Annotate a single image with numbered sheep. "
            "Provide an optional path or omit to auto-select from input/."
        ),
    )
    args = parser.parse_args()

    if args.snapshot is not None:
        _ensure_dirs()
        image_arg = None if args.snapshot == "auto" else Path(args.snapshot)
        count, chosen = annotate_single_image(image_arg)
        if count == 0:
            print("No sheep detected in the selected image. Try another photo or lower DETECTION_CONF.")
        else:
            print(f"Annotated {count} sheep in snapshot. Image: {OUTPUT_DIR / 'sheep_snapshot.jpg'}")
        return

    print("===============================")
    print("Sheep ID Pipeline")
    print("===============================")

    if not INPUT_DIR.exists():
        print(f"ERROR: '{INPUT_DIR}' does not exist. Create it and add your videos/images.")
        sys.exit(1)

    _ensure_dirs()

    print("\nSTEP 1: extract_frames")
    num_frames = extract_frames()
    if num_frames == 0:
        print("No frames extracted. Check your input files.")

    print("\nSTEP 2: detect_and_crop")
    num_crops = detect_and_crop()
    if num_crops == 0:
        print("No crops saved. Check detection settings or input content.")

    print("\nSTEP 3: cluster_and_export")
    num_clusters, _ = cluster_and_export()
    if num_clusters == 0:
        print("No clusters exported. Consider tuning DBSCAN_EPS or DBSCAN_MIN_SAMPLES.")

    print("\nDone.")


if __name__ == "__main__":
    main()

