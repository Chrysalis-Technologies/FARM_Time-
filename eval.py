import argparse
import json
import pathlib
import sys


def load_metrics(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def is_improved(new: dict, baseline: dict, key: str = "accuracy", tol: float = 1e-4) -> bool:
    if key not in new:
        return False
    if key not in baseline:
        return True
    return new[key] >= baseline[key] - tol


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)  # unused placeholder
    parser.add_argument("--metrics", required=True)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()

    new = load_metrics(pathlib.Path(args.metrics))
    baseline = load_metrics(pathlib.Path(args.baseline))
    improved = is_improved(new, baseline)

    print(f"New metrics: {new}")
    print(f"Baseline metrics: {baseline or 'none'}")
    if not improved:
        print("Regression detected; failing build.")
        sys.exit(1)
    print("Metrics improved or no baseline; passing.")

    pathlib.Path("metrics").mkdir(exist_ok=True)
    pathlib.Path("metrics/prod.json").write_text(json.dumps(new, indent=2))


if __name__ == "__main__":
    main()
