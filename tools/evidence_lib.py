"""Read-only evidence primitives; no mounting, device I/O or repair operations."""
import hashlib
import json
import os
from pathlib import Path
import stat

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = {
    'hardware/emmc/original/form3-mmcblk0-ACQUISITION04.img': (15678308352, '7527daa8cf81d4b4dfa97eeea1131c6fa84ba2c812a71c9a867ba7bcfe10bb0f'),
    'hardware/emmc/original/form3-mmcblk0boot0-ACQUISITION01.img': (4194304, 'bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8'),
    'hardware/emmc/original/form3-mmcblk0boot1-ACQUISITION02.img': (4194304, 'bb9f8df61474d25e71fa00722318cd387396ca1736605e1248821cc0de3d3af8'),
    'hardware/qspi/original/form3_qspi_FACTORY.bin': (4194304, '8a09d540d683c96227b875be1462bb0e6f9ab1ee4d0717be787e3cd1dcb4fedf'),
    'hardware/qspi/build-v2/form3_qspi_RESCUE_V2.bin': (4194304, '8a58a97cbb0bc5d52ada65debb7e195ee5935d1057a0b27096774feffdc59164'),
}

def open_evidence(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        os.close(fd)
        raise ValueError('Evidence input must be a regular file, not a device or symlink')
    return os.fdopen(fd, 'rb')

def sha256_file(path):
    h = hashlib.sha256()
    with open_evidence(path) as f:
        for block in iter(lambda: f.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()

def safe_output(path):
    p = Path(path).absolute()
    resolved = p.resolve()
    for directory in ('hardware/emmc/original', 'hardware/qspi/original'):
        if resolved.is_relative_to(ROOT / directory):
            raise ValueError('Output inside original evidence is forbidden')
    if resolved.is_relative_to('/dev') or resolved.is_relative_to('/proc') or resolved.is_relative_to('/sys'):
        raise ValueError('Output must be a workspace file')
    if p.exists() or p.is_symlink():
        raise FileExistsError(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p

def write_json(path, value):
    with safe_output(path).open('x') as f:
        json.dump(value, f, indent=2, sort_keys=True)
        f.write('\n')
