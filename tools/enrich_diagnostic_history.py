#!/usr/bin/env python3
"""Add bounded thermal history to an existing PRIVATE allowlisted panel export.

Reuses a completed export instead of rereading inaccessible extracted log trees.
Only panel metadata, summaries and enumerated raw/log-NNN.log files are copied.
Keyrings, SQLite stores and private job catalogs are not included. Original bundles
remain unchanged. This does not expand the earlier recovery/allowlist coverage.
"""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from evidence_lib import ROOT, open_evidence, safe_output, write_json
from build_diagnostic_bundle import thermal_history, decode_metrics
from panel_data import SafeTree, strict_json


def enrich(bundle, thermal, output):
    tree = SafeTree(bundle)
    try:
        snapshot_raw = tree.read('panel_snapshot.json')
        diagnostic_raw = tree.read('diagnostics.json')
        snapshot = strict_json(snapshot_raw)
        diagnostics = strict_json(diagnostic_raw)
        if (not isinstance(snapshot, dict) or snapshot.get('schema_version') != 1
                or snapshot.get('state') != 'HISTORICAL' or not isinstance(diagnostics, list)
                or len(diagnostics) > 20000):
            raise ValueError('Expected existing historical panel export')
        with open_evidence(thermal) as f:
            raw = f.read((8 << 20) + 1)
        digest = hashlib.sha256(raw).hexdigest()
        sensors = snapshot.get('sensors')
        if not isinstance(sensors, list) or len(sensors) > 64:
            raise ValueError('Invalid metric manifest')
        matches = [x for x in sensors if isinstance(x, dict) and
                   x.get('path') == 'logs/fluentbit_system_thermal.msgpack']
        if len(matches) != 1 or matches[0].get('source_sha256') != digest:
            raise ValueError('Thermal source does not match the existing export')
        matches[0]['thermal_history'] = thermal_history(decode_metrics(raw))
        logs = snapshot.get('logs')
        if not isinstance(logs, list) or len(logs) > 256:
            raise ValueError('Invalid log manifest')
        copies = {}; total = 0
        for row in logs:
            identifier = row.get('file_id') if isinstance(row, dict) else None
            if not isinstance(identifier, str) or not re.fullmatch(r'log-[0-9]{3}', identifier) or identifier in copies:
                raise ValueError('Invalid/repeated opaque log identifier')
            value = tree.read('raw/'+identifier+'.log', 8 << 20)
            if len(value) != row.get('decoded_size'):
                raise ValueError('Copied log length disagrees with previous provenance')
            total += len(value)
            if total > 64 << 20:
                raise ValueError('Total copied log budget')
            copies[identifier] = value
        out = safe_output(output)
        if not out.resolve().is_relative_to(ROOT/'research-private'):
            raise ValueError('Private output required')
        out.mkdir(mode=0o700); (out/'raw').mkdir(mode=0o700)
        receipt = {'schema_version':1, 'previous_panel_snapshot_sha256':hashlib.sha256(snapshot_raw).hexdigest(),
                   'thermal_source_sha256':digest, 'copied_logs':len(copies), 'copied_log_bytes':total,
                   'recovery_coverage_expanded':False, 'originals_modified':False,
                   'view':snapshot.get('scope'), 'raw_copies':[]}
        for identifier, value in sorted(copies.items()):
            target = out/'raw'/(identifier+'.log'); target.write_bytes(value); target.chmod(0o600)
            receipt['raw_copies'].append({'file_id':identifier,'sha256':hashlib.sha256(value).hexdigest(),'bytes':len(value)})
        for name, value in [('panel_snapshot.json',snapshot),('diagnostics.json',diagnostics),('enrichment-manifest.json',receipt)]:
            target = out/name; target.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n'); target.chmod(0o600)
        return receipt
    finally:
        tree.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--bundle', required=True); p.add_argument('--thermal', required=True)
    p.add_argument('--output', required=True); p.add_argument('--report', required=True)
    a = p.parse_args(); receipt = enrich(a.bundle,a.thermal,a.output); write_json(a.report,receipt)
    print(json.dumps({k:receipt[k] for k in ('copied_logs','copied_log_bytes','recovery_coverage_expanded','originals_modified')}))


if __name__ == '__main__':
    main()
