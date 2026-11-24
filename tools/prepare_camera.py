"""Copy the Python runtime dependency closure from the locally validated revision.

Run explicitly before committing the camera branch. No network or native execution.
"""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "custom_components/mova_nutripal/xp2p"
SOURCE = "custom_components/dreame_lawn_mower/dreame_lawn_mower_client"


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def extract_video_models(content):
    """Keep only the upstream XP2P input model and its helpers."""
    source = content.decode("utf-8")
    lines = source.splitlines(keepends=True)
    tree = ast.parse(source)

    required = {
        "DreameLawnMowerCameraStreamRuntimeInputs",
        "_credential_pair_state",
        "_missing_credential_pair",
    }

    selected = []

    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            if node.name in required:
                start = min(
                    [node.lineno]
                    + [d.lineno for d in node.decorator_list]
                )
                selected.append(
                    "".join(lines[start - 1:node.end_lineno])
                )
                required.remove(node.name)

    if required:
        raise SystemExit(
            "Missing video models: " + ", ".join(sorted(required))
        )

    header = (
        '"""Video-only model extracted from upstream MIT sources."""\n'
        "from __future__ import annotations\n"
        "from collections.abc import Mapping\n"
        "from dataclasses import asdict, dataclass, field\n"
        "from typing import Any\n"
        "from .video_provisioning_status import "
        "classify_xp2p_provisioning_issue\n\n"
    )

    return (header + "\n\n".join(selected) + "\n").encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream", type=Path)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    repo = args.upstream.resolve()
    commit = git(repo, "rev-parse", "HEAD").decode().strip()
    if args.commit != commit or len(commit) != 40:
        raise SystemExit("Use the exact validated upstream commit, with HEAD unchanged")
    # Use committed bytes, not local modifications. Walk static relative imports.
    files = {}
    queue = ["xp2p_runtime_bootstrap", "xp2p_host_runtime", "models"]
    while queue:
        name = queue.pop()
        if name in files:
            continue
        if not name.isidentifier():
            raise SystemExit("Unsupported nested dependency: " + name)
        content = git(repo, "show", f"{commit}:{SOURCE}/{name}.py")
        if name == "models":
            content = extract_video_models(content)

        files[name] = content
        tree = ast.parse(content, filename=name + ".py")
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level:
                if node.level != 1 or not node.module:
                    raise SystemExit(f"Unsupported relative import in {name}")
                queue.append(node.module)
    license_bytes = git(repo, "show", f"{commit}:LICENSE")
    if TARGET.exists():
        raise SystemExit(f"Target already exists: {TARGET}; review before replacing it")
    with tempfile.TemporaryDirectory(dir=TARGET.parent) as temp:
        staging = Path(temp) / "xp2p"
        staging.mkdir()
        (staging / "__init__.py").write_text('"""Isolated MIT-licensed upstream runtime; no mower integration import."""\n')
        for name, content in sorted(files.items()):
            (staging / (name + ".py")).write_bytes(content)
        (staging / "LICENSE").write_bytes(license_bytes)
        (staging / "UPSTREAM_COMMIT").write_text(commit + "\n")
        staging.rename(TARGET)
    print(f"Prepared {len(files)} modules from {commit}")
    print("Review and commit the copied sources, license and commit marker.")


if __name__ == "__main__":
    main()
