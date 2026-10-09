#!/usr/bin/env python3
"""Host import wrapper for the single authored runtime read-only W1 reader."""
import importlib.util
from pathlib import Path
path=Path(__file__).resolve().parents[1]/'owner-maintenance'/'read_ds2431_protection.py'
spec=importlib.util.spec_from_file_location('owner_w1_protection',str(path))
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
crc8=module.crc8
validate_rom=module.validate_rom
request=module.request
parse_reply=module.parse_reply
read_memory=module.read_memory
protection_summary=module.protection_summary
