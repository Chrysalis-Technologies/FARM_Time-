"""Identify individual sheep across a photo set and group their crops.

The script runs a lightweight detection-and-tracking pass over a directory of
images:

1. A pre-trained COCO Faster R-CNN model finds sheep instances in each image.
2. Each detected sheep is cropped and described with a compact color feature
   vector derived from its coat palette.
3. Detected sheep are matched to previously seen individuals using cosine
   similarity on the feature vectors. Crops belonging to the same sheep are
   grouped into a dedicated output folder.

This is a heuristic pipeline intended for quick field use; it avoids any
fine-tuning by leaning on the general COCO model and color-based matching. The
output manifest can be inspected or post-processed to refine matches if
needed.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import torch
from PIL import Image
from torchvision import transforms
from torchvision.models.detection import (
    FasterRCNN_ResNet50_FPN_Weights,
    fasterrcnn_resnet50_fpn,
)

from coat_pattern import find_images, quantized_palette, Palette


COCO_LABELS = FasterRCNN_ResNet50_FPN_Weights.COCO_V1.meta["categories"]
SHEEP_INDEX = COCO_LABELS.index("sheep") + 1  # COCO labels are 1-indexed


@dataclass
class SheepDetection:
    """A single detected sheep in one image."""

    image_path: Path
    bbox: Tuple[int, int, int, int]  # (left, top, right, bottom)
    score: float
    palette: Palette
    feature_vector: List[float]

    def crop(self) -> Image.Image:
        with Image.open(self.image_path) as image:
            return image.convert("RGB").crop(self.bbox)


@dataclass
class SheepTrack:
    """Aggregate of detections believed to belong to the same sheep."""

    track_id: int
    detections: List[SheepDetection] = field(default_factory=list)
    feature_vector: List[float] = field(default_factory=list)

    def update(self, detection: SheepDetection) -> None:
        self.detections.append(detection)
        if not self.feature_vector:
            self.feature_vector = detection.feature_vector
            return

        # Running average to keep the centroid stable as we add detections.
        for idx, value in enumerate(detection.feature_vector):
            previous = self.feature_vector[idx]
            self.feature_vector[idx] = previous + (value - previous) / len(
                self.detections
            )


def cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 1.0
    return 1 - (dot / (norm_a * norm_b))


def build_feature_vector(palette: Palette, top_n: int = 4) -> List[float]:
    """Flatten palette entries into a compact feature vector.

    Each entry contributes ``(share, r, g, b)`` where RGB values are normalized
    to 0..1. Missing entries are padded with zeros for consistent length.
    """

    vector: List[float] = []
    for color, share in palette[:top_n]:
        r, g, b = color
        vector.extend([share, r / 255, g / 255, b / 255])

    expected_length = top_n * 4
    if len(vector) < expected_length:
        vector.extend([0.0] * (expected_length - len(vector)))
    return vector


def load_model(device: torch.device) -> torch.nn.Module:
    weights = FasterRCNN_ResNet50_FPN_Weights.DEFAULT
    model = fasterrcnn_resnet50_fpn(weights=weights)
    model.eval().to(device)
    return model


def detect_sheep(
    image_path: Path, model: torch.nn.Module, device: torch.device, score_threshold: float
) -> Iterable[SheepDetection]:
    transform = transforms.Compose([transforms.ToTensor()])
    with Image.open(image_path) as image:
        rgb_image = image.convert("RGB")
        tensor = transform(rgb_image).to(device)

    with torch.no_grad():
        outputs = model([tensor])[0]

    for box, score, label in zip(
        outputs["boxes"].cpu(), outputs["scores"].cpu(), outputs["labels"].cpu()
    ):
        if score.item() < score_threshold:
            continue
        if int(label.item()) != SHEEP_INDEX:
            continue

        left, top, right, bottom = [int(round(x)) for x in box.tolist()]
        palette = quantized_palette(rgb_image.crop((left, top, right, bottom)))
        yield SheepDetection(
            image_path=image_path,
            bbox=(left, top, right, bottom),
            score=float(score.item()),
            palette=palette,
            feature_vector=build_feature_vector(palette),
        )


def match_track(detection: SheepDetection, tracks: List[SheepTrack], max_distance: float) -> int:
    best_track = None
    best_distance = max_distance

    for track in tracks:
        distance = cosine_distance(detection.feature_vector, track.feature_vector)
        if distance < best_distance:
            best_distance = distance
            best_track = track

    if best_track:
        best_track.update(detection)
        return best_track.track_id

    new_id = len(tracks) + 1
    tracks.append(SheepTrack(track_id=new_id, detections=[detection], feature_vector=list(detection.feature_vector)))
    return new_id


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def save_crop(detection: SheepDetection, track_id: int, output_root: Path) -> Path:
    crop_dir = output_root / f"sheep_{track_id:03d}"
    ensure_dir(crop_dir)
    crop = detection.crop()
    filename = f"{detection.image_path.stem}_score{detection.score:.2f}.jpg"
    output_path = crop_dir / filename
    crop.save(output_path)
    return output_path


def write_manifest(tracks: List[SheepTrack], output_root: Path) -> None:
    manifest = {
        "sheep": [
            {
                "sheep_id": track.track_id,
                "detections": [
                    {
                        "source_image": str(det.image_path),
                        "bbox": det.bbox,
                        "score": det.score,
                        "palette": det.palette,
                    }
                    for det in track.detections
                ],
            }
            for track in tracks
        ]
    }

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))


def process_directory(
    input_dir: Path,
    output_dir: Path,
    score_threshold: float = 0.65,
    max_match_distance: float = 0.2,
) -> List[SheepTrack]:
    ensure_dir(output_dir)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = load_model(device)

    tracks: List[SheepTrack] = []

    images = sorted(find_images(input_dir))
    if not images:
        raise FileNotFoundError(f"No images found under {input_dir}")

    for image_path in images:
        for detection in detect_sheep(image_path, model, device, score_threshold):
            track_id = match_track(detection, tracks, max_match_distance)
            save_crop(detection, track_id, output_dir)

    write_manifest(tracks, output_dir)
    return tracks


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Detect and group individual sheep across a folder of photos."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("sheep_ids/input"),
        help="Directory containing sheep photos (searches recursively).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sheep_ids/output"),
        help="Folder where cropped sheep and manifest will be written.",
    )
    parser.add_argument(
        "--score-threshold",
        type=float,
        default=0.65,
        help="Minimum detector confidence for a sheep bounding box.",
    )
    parser.add_argument(
        "--match-distance",
        type=float,
        default=0.2,
        help="Maximum cosine distance for considering two detections the same sheep.",
    )
    args = parser.parse_args(argv)

    tracks = process_directory(
        input_dir=args.dir,
        output_dir=args.output,
        score_threshold=args.score_threshold,
        max_match_distance=args.match_distance,
    )

    print(f"Grouped {sum(len(t.detections) for t in tracks)} sheep detections into {len(tracks)} unique sheep folders.")
    print(f"Crops and manifest written to {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
