"""emerge-ai overlay repository (spec: repair-ladder): copy-fix ebuilds win via
priority, every copy is registered with source, reason and journal id."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

OVERLAY_ROOT = "/var/lib/emerge-ai/overlay"
REPOS_CONF = "/etc/portage/repos.conf"
REPO_NAME = "emerge-ai"
REGISTRY = "registry.json"


def repos_conf_entry(name: str = REPO_NAME, location: str = OVERLAY_ROOT, priority: int = 99) -> str:
    return (
        f"[{name}]\n"
        f"location = {location}\n"
        f"priority = {priority}\n"
        f"auto-sync = false\n"
    )


def ensure_layout(
    repo_root: str | Path,
    repos_conf_dir: str | Path | None = None,
    *,
    name: str = REPO_NAME,
    priority: int = 99,
    masters: str = "gentoo",
) -> Path:
    root = Path(repo_root)
    (root / "profiles").mkdir(parents=True, exist_ok=True)
    conf = root / "profiles" / "repo_name"
    if not conf.exists():
        conf.write_text(f"{name}\n")
    layout = root / "metadata" / "layout.conf"
    if masters and not layout.exists():
        layout.parent.mkdir(parents=True, exist_ok=True)
        layout.write_text(f"masters = {masters}\n")
    if repos_conf_dir is not None:
        d = Path(repos_conf_dir)
        d.mkdir(parents=True, exist_ok=True)
        target = d / f"{name}.conf"
        if not target.exists():
            entry = repos_conf_entry(name, str(root), priority)
            if masters:
                entry += f"masters = {masters}\n"
            target.write_text(entry)
    return root


def _registry_path(repo_root: Path) -> Path:
    return repo_root / REGISTRY


def load_registry(repo_root: str | Path) -> dict:
    p = _registry_path(Path(repo_root))
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _digest_manifest_args(path: Path) -> str:
    import hashlib

    data = path.read_bytes()
    h = lambda alg: hashlib.new(alg, data).hexdigest()  # noqa: E731
    return (
        f"MD5 {h('md5')} SHA1 {h('sha1')} SHA256 {h('sha256')} "
        f"SHA512 {h('sha512')} SIZE {len(data)}"
    )


def write_manifest(dest_dir: Path, names: list[str]) -> Path:
    lines = []
    for name in sorted(names):
        p = dest_dir / name
        if not p.is_file() or name == "Manifest":
            continue
        ftype = "EBUILD" if name.endswith(".ebuild") else "AUX"
        lines.append(f"{ftype} {name} {_digest_manifest_args(p)}")
    manifest = dest_dir / "Manifest"
    manifest.write_text("".join(l + "\n" for l in lines))
    return manifest


def add_package(
    cpv: str,
    *,
    repo_root: str | Path = OVERLAY_ROOT,
    source_dir: str | Path,
    reason: str,
    journal_id: str = "",
    ebuild_cmd: list[str] | None = None,
) -> dict:
    """Copy an ebuild from the source tree into the overlay, regenerate the
    Manifest via `ebuild ... manifest`, register the entry."""
    cat, pn, pv = _split_cpv(cpv)
    source = Path(source_dir)
    ebuild = source / f"{pn}-{pv}.ebuild"
    if not ebuild.exists():
        raise FileNotFoundError(f"source ebuild missing: {ebuild}")
    dest = Path(repo_root) / cat / pn
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ebuild, dest / ebuild.name)
    for extra in source.glob(f"{pn}-{pv}.ebuild.*"):  # ebuild-side files (files/, digests)
        shutil.copy2(extra, dest / extra.name)
    files_src = source.parent / "files" / pv
    if files_src.is_dir():
        files_dst = Path(repo_root) / cat / "files" / pv
        if files_dst.exists():
            shutil.rmtree(files_dst)
        shutil.copytree(files_src, files_dst)
    if ebuild_cmd is not None:
        cmd = list(ebuild_cmd) + [str(dest / ebuild.name), "manifest"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"ebuild manifest failed rc={proc.returncode}: {proc.stderr[-400:]}")
        if not (dest / "Manifest").exists():
            raise RuntimeError("manifest command produced no Manifest file")
    else:
        write_manifest(dest, [f.name for f in dest.iterdir()])
    entry = {
        "cpv": cpv,
        "source": str(source),
        "reason": reason,
        "journal_id": journal_id,
        "ts": time.time(),
    }
    registry = load_registry(repo_root)
    registry[cpv] = entry
    _registry_path(Path(repo_root)).write_text(json.dumps(registry, indent=2, ensure_ascii=False))
    return entry


def remove_package(cpv: str, *, repo_root: str | Path = OVERLAY_ROOT) -> bool:
    """Explicit human decision only (GC suggestion must be confirmed elsewhere)."""
    cat, pn, pv = _split_cpv(cpv)
    reg = load_registry(repo_root)
    removed = reg.pop(cpv, None) is not None
    _registry_path(Path(repo_root)).write_text(json.dumps(reg, indent=2, ensure_ascii=False))
    ebuild = Path(repo_root) / cat / pn / f"{pn}-{pv}.ebuild"
    if ebuild.exists():
        ebuild.unlink()
    return removed


def _split_cpv(cpv: str) -> tuple[str, str, str]:
    cat, rest = cpv.split("/", 1)
    pn = rest.rsplit("-", 1)[0]
    pv = rest.rsplit("-", 1)[1]
    return cat, pn, pv
