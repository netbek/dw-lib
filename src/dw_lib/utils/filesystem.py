from pathlib import Path

import shutil


def get_file_extension(path: Path | str) -> str | None:
    path = Path(path)
    return path.suffix or None


def get_file_name(path: Path | str) -> str:
    path = Path(path)
    return path.stem


def find_up(path: Path | str, pattern: str) -> Path | None:
    path = Path(path)

    if path.is_file():
        return find_up(path.parent, pattern)

    matches = list(path.glob(pattern))
    if matches:
        return matches[0]

    if path == path.parent:
        return None

    return find_up(path.parent, pattern)


def copy(src: Path | str, dst: Path | str):
    src, dst = Path(src), Path(dst)

    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst, symlinks=True)
    else:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def symlink(src: Path | str, dst: Path | str):
    src, dst = Path(src), Path(dst)
    if dst.is_symlink() or dst.exists():
        dst.unlink()
    dst.symlink_to(src)


def rmtree(path: Path | str):
    path = Path(path)
    if path.exists():
        shutil.rmtree(path)


def touch(path: Path | str):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
