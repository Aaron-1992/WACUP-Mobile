"""Importer registry.

A format is a module exposing ``EXTENSIONS``, ``LABEL`` and ``read(path) -> Song``.
Dropping a new module here and registering it is all it takes to support another
game-music format — that is the "extension" side of the tool.
"""

import os
import sys
import tempfile
import zipfile
from typing import Callable, Dict, List, Tuple

_REGISTRY: Dict[str, Callable] = {}
_LABELS: Dict[str, str] = {}
_ORDER: List[str] = []


def register(name: str, label: str):
    def decorator(function):
        _REGISTRY[name] = function
        _LABELS[name] = label
        _ORDER.append(name)
        return function
    return decorator


def _load_builtin() -> None:
    # These are imported by name, not by string, so that a frozen executable
    # (PyInstaller) can see them at build time as well as at run time.
    if _REGISTRY:
        return
    for module_name, loader in (
            ("midi", _import_midi),
            ("vgm", _import_vgm),
            ("gym", _import_gym),
            ("nds", _import_ds)):
        try:
            loader()
        except Exception as exc:      # a broken importer must not kill the tool
            _LABELS[module_name] = "unavailable (%s)" % exc


def _import_midi():
    from . import midi          # noqa: F401  (registers itself on import)
    return midi


def _import_vgm():
    from . import vgm           # noqa: F401
    return vgm


def _import_gym():
    from . import gym           # noqa: F401
    return gym


def _import_ds():
    from . import ds            # noqa: F401
    return ds


def available() -> List[Tuple[str, str]]:
    _load_builtin()
    return [(name, _LABELS.get(name, name)) for name in _ORDER]


SUPPORTED_INSIDE_ZIP = (".vgm", ".vgz", ".gym", ".mid", ".midi", ".rmi",
                        ".sseq", ".sdat")


def _from_zip(path: str) -> Callable:
    """Music packs are usually zipped; pull the first file we can read out of it."""
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if os.path.splitext(name)[1].lower() in SUPPORTED_INSIDE_ZIP:
                payload = archive.read(name)
                handle, temp_path = tempfile.mkstemp(
                    suffix=os.path.splitext(name)[1] or ".bin")
                with os.fdopen(handle, "wb") as out:
                    out.write(payload)
                inner = find_for(temp_path)

                def extract(_original, _temp=temp_path, _reader=inner):
                    try:
                        return _reader(_temp)
                    finally:
                        try:
                            os.unlink(_temp)
                        except OSError:
                            pass

                return extract
    raise ValueError("no MIDI/VGM/GYM file inside %s" % path)


def find_for(path: str) -> Callable:
    """Pick an importer by extension, falling back to magic-byte sniffing."""
    _load_builtin()
    if os.path.splitext(path)[1].lower() == ".zip":
        return _from_zip(path)
    extension = os.path.splitext(path)[1].lower().lstrip(".")
    if extension == "gz":
        extension = os.path.splitext(os.path.splitext(path)[0])[1].lower().lstrip(".")

    candidates = {
        "mid": "midi", "midi": "midi", "rmi": "midi", "kar": "midi",
        "vgm": "vgm", "vgz": "vgm", "vgm.gz": "vgm",
        "gym": "gym", "gym.gz": "gym",
        "nds": "nds", "sdat": "nds", "sseq": "nds",
    }
    name = candidates.get(extension)
    if name and name in _REGISTRY:
        return _REGISTRY[name]

    sniffed = _sniff(path)
    if sniffed and sniffed in _REGISTRY:
        return _REGISTRY[sniffed]
    raise ValueError(
        "No importer for '%s'. Known formats: %s"
        % (path, ", ".join(name for name, _ in available()))
    )


def module_of(importer):
    """The module an importer function came from (for format-specific extras)."""
    return sys.modules.get(getattr(importer, "__module__", ""))


def read_source(path: str, settings=None):
    """Read a file with whatever the format needs from the settings.

    DS ROMs need to know *which* sequence and bank of the archive to use; the
    other importers just take a path, so they are asked exactly as before.
    """
    _load_builtin()
    importer = find_for(path)
    module = module_of(importer)
    optional = getattr(module, "read_with", None) if module else None
    if optional is not None:
        try:
            return optional(path, settings)
        except TypeError:
            pass
    return importer(path)


def extract_assets(path: str, directory: str, stem: str) -> List[str]:
    """Ask a format's importer to write its source material out (MIDI, SF2…)."""
    _load_builtin()
    try:
        importer = find_for(path)
    except Exception:
        return []
    module = module_of(importer)
    writer = getattr(module, "assets", None) if module else None
    if writer is None:
        return []
    try:
        return writer(path, directory, stem) or []
    except Exception:
        return []


def _sniff(path: str):
    try:
        with open(path, "rb") as handle:
            head = handle.read(16)
    except OSError:
        return None
    if head[:4] == b"MThd":
        return "midi"
    if head[:4] == b"RIFF" and head[8:12] == b"RMID":
        return "midi"
    if head[:4] == b"Vgm ":
        return "vgm"
    if head[:4] in (b"SSEQ", b"SDAT"):
        return "nds"
    if head[:3] == b"GYM":
        return "gym"
    if head[:2] == b"\x1f\x8b":       # gzip: peek inside
        try:
            import gzip
            with gzip.open(path, "rb") as inner:
                inner_head = inner.read(16)
            if inner_head[:4] == b"Vgm ":
                return "vgm"
            if inner_head[:3] == b"GYM":
                return "gym"
        except Exception:
            return None
    return None
