import argparse
import json
import pathlib
import random
import time


def fake_train(data_dir: str) -> dict:
    """Placeholder training function; replace with real training logic."""
    random.seed(0)  # deterministic stub
    acc = 0.80 + random.random() * 0.05
    loss = 0.5 + random.random() * 0.1
    return {
        "accuracy": round(acc, 4),
        "loss": round(loss, 4),
        "timestamp": time.time(),
        "data_dir": data_dir,
    }


def save_dummy_model(out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "model.pt").write_text("placeholder model bytes")
    (out_dir / "README.txt").write_text(
        "Replace with real model artifact (torchscript/onnx/etc)."
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    out_dir = pathlib.Path(args.out)
    metrics = fake_train(args.data)
    save_dummy_model(out_dir)
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
