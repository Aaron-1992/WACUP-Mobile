"""Native file dialogs and shell helpers, without any GUI toolkit.

On Windows the real common dialogs are called through ctypes, so the app keeps
its "no dependencies beyond pygame" promise while still having a proper
"Open file" and "Save as" window. Elsewhere it falls back to whatever the system
provides (zenity, kdialog, osascript) and, if nothing is available, the app tells
the user to drag files in instead.
"""

import os
import subprocess
import sys
from typing import List, Optional

FILTER = "Music files (*.mid;*.midi;*.rmi;*.kar;*.vgm;*.vgz;*.gym;*.zip)|*.mid;*.midi;*.rmi;*.kar;*.vgm;*.vgz;*.gym;*.zip|All files (*.*)|*.*|"


def _windows_owner():
    try:
        import pygame
        info = pygame.display.get_wm_info()
        return info.get("window") or 0
    except Exception:
        return 0


def _windows_open() -> Optional[List[str]]:
    import ctypes
    from ctypes import wintypes

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", ctypes.c_void_p),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    OFN_EXPLORER = 0x00080000
    OFN_FILEMUSTEXIST = 0x00001000
    OFN_ALLOWMULTISELECT = 0x00000200
    OFN_NOCHANGEDIR = 0x00000008
    OFN_PATHMUSTEXIST = 0x00000800

    size = 65536
    buffer = ctypes.create_unicode_buffer(size)
    dialog = OPENFILENAMEW()
    dialog.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    dialog.hwndOwner = _windows_owner()
    dialog.lpstrFilter = FILTER.replace("|", "\0")
    dialog.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    dialog.nMaxFile = size
    dialog.lpstrTitle = "Add music to chip8bit"
    dialog.Flags = (OFN_EXPLORER | OFN_FILEMUSTEXIST | OFN_ALLOWMULTISELECT
                    | OFN_NOCHANGEDIR | OFN_PATHMUSTEXIST)

    if not ctypes.windll.comdlg32.GetOpenFileNameW(ctypes.byref(dialog)):
        return None

    parts = buffer[:].split("\0")
    if len(parts) <= 1:
        return [parts[0]] if parts and parts[0] else None
    directory = parts[0]
    return [os.path.join(directory, name) for name in parts[1:] if name]


def _windows_save(default_name: str) -> Optional[str]:
    import ctypes
    from ctypes import wintypes

    class OPENFILENAMEW(ctypes.Structure):
        _fields_ = [
            ("lStructSize", wintypes.DWORD),
            ("hwndOwner", wintypes.HWND),
            ("lpstrFilter", wintypes.LPCWSTR),
            ("lpstrCustomFilter", wintypes.LPWSTR),
            ("nMaxCustFilter", wintypes.DWORD),
            ("nFilterIndex", wintypes.DWORD),
            ("lpstrFile", wintypes.LPWSTR),
            ("nMaxFile", wintypes.DWORD),
            ("lpstrFileTitle", wintypes.LPWSTR),
            ("nMaxFileTitle", wintypes.DWORD),
            ("lpstrInitialDir", wintypes.LPCWSTR),
            ("lpstrTitle", wintypes.LPCWSTR),
            ("Flags", wintypes.DWORD),
            ("nFileOffset", wintypes.WORD),
            ("nFileExtension", wintypes.WORD),
            ("lpstrDefExt", wintypes.LPCWSTR),
            ("lCustData", ctypes.c_void_p),
            ("lpfnHook", ctypes.c_void_p),
            ("lpTemplateName", wintypes.LPCWSTR),
            ("pvReserved", ctypes.c_void_p),
            ("dwReserved", wintypes.DWORD),
            ("FlagsEx", wintypes.DWORD),
        ]

    OFN_OVERWRITEPROMPT = 0x00000002
    OFN_EXPLORER = 0x00080000
    OFN_NOCHANGEDIR = 0x00000008

    buffer = ctypes.create_unicode_buffer(default_name, 4096)
    wave_filter = ("Wave audio (*.wav)|*.wav|All files (*.*)|*.*|").replace("|", "\0")
    dialog = OPENFILENAMEW()
    dialog.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    dialog.hwndOwner = _windows_owner()
    dialog.lpstrFilter = wave_filter
    dialog.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    dialog.nMaxFile = 4096
    dialog.lpstrTitle = "Save the 8-bit version as"
    dialog.lpstrDefExt = "wav"
    dialog.Flags = OFN_OVERWRITEPROMPT | OFN_EXPLORER | OFN_NOCHANGEDIR

    if not ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(dialog)):
        return None
    return buffer.value or None


def _run(command: List[str]) -> Optional[str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    except Exception:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip() or None


def _posix_open() -> Optional[List[str]]:
    if sys.platform == "darwin":
        result = _run(["osascript", "-e",
                       'POSIX path of (choose file with prompt "Add music" '
                       'of type {"public.item"} with multiple selections allowed)'])
        return [result] if result else None
    result = _run(["zenity", "--file-selection", "--multiple", "--separator=\n",
                   "--title=Add music to chip8bit"])
    if result:
        return [line for line in result.splitlines() if line]
    result = _run(["kdialog", "--getopenfilename", os.path.expanduser("~"),
                   "*.mid *.midi *.vgm *.vgz *.gym *.zip"])
    return [result] if result else None


def _posix_save(default_name: str) -> Optional[str]:
    if sys.platform == "darwin":
        return _run(["osascript", "-e",
                     'POSIX path of (choose file name with prompt "Save as" '
                     'default name "%s")' % default_name])
    result = _run(["zenity", "--file-selection", "--save", "--confirm-overwrite",
                   "--filename=%s" % default_name])
    if result:
        return result
    return _run(["kdialog", "--getsavefilename", default_name, "*.wav"])


def open_files() -> Optional[List[str]]:
    """Ask the system for files. None means "the user cancelled or cannot"."""
    try:
        if os.name == "nt":
            return _windows_open()
        return _posix_open()
    except Exception:
        return None


def save_as(default_name: str) -> Optional[str]:
    try:
        if os.name == "nt":
            return _windows_save(default_name)
        return _posix_save(default_name)
    except Exception:
        return None


def reveal(path: str) -> None:
    """Open a folder (or highlight a file) in the system file manager."""
    try:
        if os.name == "nt":
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(os.path.dirname(path) or path)      # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", path] if os.path.isfile(path)
                             else ["open", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or path])
    except Exception:
        pass


def default_output_dir() -> str:
    for candidate in (os.path.join(os.path.expanduser("~"), "Music", "chip8bit"),
                      os.path.join(os.path.expanduser("~"), "chip8bit")):
        try:
            os.makedirs(candidate, exist_ok=True)
            return candidate
        except OSError:
            continue
    return os.getcwd()
