#!/usr/bin/env python3
"""Bounded offline comparison of copied CleaningMeshes JSON, never a profile writer.

Arrays are single parameter values, not independently tunable indexed controls.
Unknown keys/strings are counted but never emitted. Numeric values are emitted
only for an explicit parameter allowlist when --include-values is requested.
No device, network, activation, firmware execution or calibration mutation.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat

MAX_BYTES = 2 * 1024 * 1024
MAX_PROFILES = 64
GROUPS = ('Material_Daguerre_Print', 'Daguerre_Print', 'Material_Form2_Print')
PARAMETERS = {
    'Material_Daguerre_Print': (
        'energyDensity_fill_mJpcm2', 'energyDensity_interiorFill_mJpcm2',
        'energyDensity_supportsFill_mJpcm2', 'energyDensity_maxForSinglePass_mJpcm2',
        'overhang_energyDensity_mJpcm2', 'earlyLayerExposures_mJpcm2',
        'earlyLayerHeights_mm', 'resin_densityLiquid_gpmL',
        'resin_flowMinimum_mLps', 'resin_flowMaximum_mLps',
        'roller_squeezeSpeed_mmps', 'roller_maxSynchronizedAcceleration_mmps2',
        'roller_postLaserCureWait_s', 'fill_skinThickness_mm',
        'dimensionalAccuracy_outerBoundaryOffset_mm', 'edgeSharpening_width_mm'),
    'Daguerre_Print': ('laser_maxAllowablePower_mW', 'laser_minAllowableFillPower_mW',
                      'wipe_speed_mmps', 'wipe_distance_mm', 'peel_liftSpeeds_mmps',
                      'peel_preloadSpeeds_mmps'),
    'Material_Form2_Print': ('heater_minimumTemperature_C',
                           'heater_startTemperature_C', 'heater_setPoint_C'),
}


def reject(message):
    raise ValueError(message)


def no_symlinks(path):
    path = Path(os.path.abspath(path))
    if any(p.is_symlink() for p in (path,) + tuple(path.parents)):
        reject('Symlink input/output path rejected')
    return path


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            reject('Duplicate JSON member')
        result[key] = value
    return result


def flatten(value):
    """Flatten dictionaries; arrays/empty containers remain one leaf."""
    leaves = {}
    count = [0]

    def visit(node, path=(), depth=0, emit=True):
        count[0] += 1
        if depth > 32 or count[0] > 50000:
            reject('JSON structure bound exceeded')
        if isinstance(node, float) and not math.isfinite(node):
            reject('Nonfinite JSON number')
        if isinstance(node, dict) and node:
            for key, item in node.items():
                visit(item, path + (key,), depth + 1, emit)
        elif isinstance(node, list):
            if len(node) > 2048:
                reject('JSON array bound exceeded')
            for item in node:
                visit(item, path, depth + 1, False)
            if emit:
                leaves[path] = json.dumps(node, sort_keys=True, separators=(',', ':'))
        elif emit:
            leaves[path] = json.dumps(node, sort_keys=True, separators=(',', ':'))
    visit(value)
    return leaves


def read_json(path):
    path = no_symlinks(path)
    fd = os.open(str(path), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            reject('Expected bounded regular JSON input')
        raw = stream.read(MAX_BYTES + 1)
        after = os.fstat(stream.fileno())
        if len(raw) != before.st_size or len(raw) > MAX_BYTES or before.st_mtime_ns != after.st_mtime_ns:
            reject('Input changed or exceeded bound')
    try:
        value = json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                           parse_constant=lambda _: reject('Nonfinite JSON number'))
        if type(value) is not dict:
            reject('Expected JSON object')
        flattened = flatten(value)
    except (ValueError, UnicodeError, RecursionError):
        reject('Malformed or excessive JSON input')
    return value, flattened, hashlib.sha256(raw).hexdigest()


def material_code(value):
    return value if isinstance(value, str) and re.fullmatch(r'FL[A-Z0-9]{6,12}', value) else None


def compare_rows(rows):
    paths = set().union(*(set(r) for r in rows))
    constant = sum(all(p in r and r[p] == rows[0].get(p) for r in rows) for p in paths)
    absent = sum(any(p not in r for r in rows) for p in paths)
    return {'union': len(paths), 'constant': constant,
            'varying_or_absent': len(paths) - constant, 'absent_in_some': absent}


def numeric(value):
    return type(value) in (int, float) or (isinstance(value, list) and all(numeric(v) for v in value))


def inspect(root, include_values=False):
    root = no_symlinks(root)
    children = []
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_symlink():
                reject('Symlink in profile directory')
            if not entry.is_dir(follow_symlinks=False):
                reject('Expected profile subdirectories only')
            children.append(Path(entry.path))
            if len(children) > MAX_PROFILES:
                reject('Too many profiles')
    if not children:
        reject('No profiles found')
    reports, flat_rows, grouped = [], [], {g: [] for g in GROUPS}
    for child in sorted(children):
        value, flat, digest = read_json(child / 'all_knobs_settings.json')
        scene = value.get('Material_Scene', {})
        if not isinstance(scene, dict):
            reject('Invalid material scene')
        code = material_code(scene.get('identifier_materialCode'))
        row = {'profile_sha256': digest, 'leaf_parameters': len(flat), 'material_code': code,
               'runtime_consumers_proven': False, 'editable_range_proven': False}
        flat_rows.append(flat)
        for group in GROUPS:
            item = value.get(group, {})
            if not isinstance(item, dict):
                reject('Invalid parameter group')
            grouped[group].append(flatten(item) if item else {})
        job_path = child / 'Job.json'
        row['job'] = {'status': 'MISSING'}
        if job_path.exists() or job_path.is_symlink():
            job, _, job_digest = read_json(job_path)
            job_code = material_code(job.get('MaterialCode'))
            row['job'] = {'status': 'READ', 'sha256': job_digest, 'material_code': job_code,
                          'material_match': None if code is None or job_code is None else code == job_code}
        override_path = child / 'overridden_knobs_settings.json'
        row['overrides'] = {'status': 'MISSING'}
        if override_path.exists() or override_path.is_symlink():
            override, _, override_digest = read_json(override_path)
            row['overrides'] = {'status': 'READ', 'sha256': override_digest, 'empty': not override}
        if include_values:
            row['selected_numeric_values'] = {
                group + '.' + key: value[group][key]
                for group, names in PARAMETERS.items() for key in names
                if key in value.get(group, {}) and numeric(value[group][key])}
        reports.append(row)
    return {'schema': 1, 'evidence_level': 'FILES_ONLY', 'context': 'explicit copied profile collection',
            'arrays_counted_as': 'one parameter per array', 'profiles': reports,
            'comparison': compare_rows(flat_rows),
            'groups': {g: compare_rows(rows) for g, rows in grouped.items()},
            'all_materials_covered': False, 'device_writes': False, 'network_access': False,
            'license_activation': False, 'safe_to_apply': False}


def write_report(path, report):
    path = no_symlinks(path)
    if any(str(path) == p or str(path).startswith(p + '/') for p in ('/dev', '/sys', '/proc')):
        reject('Output must be an ordinary workspace file')
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', help='Copied CleaningMeshes directory, not a device or live mount')
    parser.add_argument('--output', required=True, help='New private report; parent must exist')
    parser.add_argument('--include-values', action='store_true', help='Include only allowlisted numeric parameters')
    args = parser.parse_args()
    try:
        result = inspect(args.directory, args.include_values)
        write_report(args.output, result)
    except (ValueError, OSError):
        parser.exit(1, 'Profile inspection failed: invalid/bounded input or unavailable fresh output. No device write.\n')
    print('Offline comparison saved; no device or license changes.')


if __name__ == '__main__':
    main()
