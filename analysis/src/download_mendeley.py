"""Download the Mendeley multimodal freezing-of-gait dataset (about 3.9 GB) into data/mendeley/raw/.

Dataset: Li et al., "Multimodal Dataset of Freezing of Gait in Parkinson's Disease",
https://data.mendeley.com/datasets/r8gmbtv7w2/3 (CC BY 4.0).

Files that already exist with the right size are skipped, so the script can be
re-run after an interruption.

Usage: python src/download_mendeley.py
"""

import json
import shutil
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root
OUT_DIR = ROOT / "data" / "mendeley" / "raw"

API = "https://data.mendeley.com/public-api/datasets/r8gmbtv7w2"
VERSION = 3
HEADERS = {"Accept": "application/vnd.mendeley-public-dataset.1+json", "User-Agent": "curl/8.0"}


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=60) as r:
        return json.load(r)


def folder_paths(folders):
    """Map folder id -> relative path, dropping the top-level 'Filtered Data' folder."""
    by_id = {f["id"]: f for f in folders}
    paths = {}
    for f in folders:
        parts, node = [], f
        while node:
            parts.append(node["name"])
            node = by_id.get(node.get("parent_id"))
        parts = [p for p in reversed(parts) if p != "Filtered Data"]
        paths[f["id"]] = Path(*parts) if parts else Path()
    return paths


def main():
    folders = get_json(f"{API}/folders/{VERSION}")
    paths = folder_paths(folders)
    todo = [(Path(), f) for f in get_json(f"{API}/files?folder_id=root&version={VERSION}")]
    for folder_id, rel in paths.items():
        todo += [(rel, f) for f in get_json(f"{API}/files?folder_id={folder_id}&version={VERSION}")]

    total = sum(f["size"] for _, f in todo)
    print(f"{len(todo)} files, {total / 1e9:.2f} GB -> {OUT_DIR}", flush=True)
    done = 0
    for rel, f in sorted(todo, key=lambda item: str(item[0] / item[1]["filename"])):
        target = OUT_DIR / rel / f["filename"]
        done += f["size"]
        if target.exists() and target.stat().st_size == f["size"]:
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(f["content_details"]["download_url"], headers=HEADERS)
        with urllib.request.urlopen(request, timeout=120) as r, open(partial, "wb") as out:
            shutil.copyfileobj(r, out, 1 << 20)
        if partial.stat().st_size != f["size"]:
            raise SystemExit(f"{target}: got {partial.stat().st_size} bytes, expected {f['size']}")
        partial.replace(target)
        print(f"  {rel / f['filename']}  ({done / total:.0%})", flush=True)
    print("Done.")


if __name__ == "__main__":
    main()
