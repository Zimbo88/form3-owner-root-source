#!/usr/bin/env python3
"""Bounded OFFLINE model of selected C/0 cartridge reconciliation decisions.

Synthetic demo only. Does not read a device, authenticate a record, encode memory,
stop a daemon, reset a counter, apply privacy settings or authorize dispensing.
Reference: pinned 2.5.6-2773 TankCartridgeDaemon; see CARTRIDGE_RECONCILIATION.md.
"""
import argparse
import json
import math

from evidence_lib import write_json

FIELDS = ('EstimatedVolumeDispensed_ml', 'CumulativeDispenseTime_s',
          'DispenseCount', 'WriteCount')


def validate_usage(value):
    if not isinstance(value, dict):
        raise ValueError('Expected a usage projection')
    limits = (6553.5, 65535, 0xffffff, 0xffffffff)
    for field, limit in zip(FIELDS, limits):
        item = value.get(field)
        if type(item) not in (int, float) or not math.isfinite(item) or not 0 <= item <= limit:
            raise ValueError('Missing, non-finite or unrepresentable usage field')
        if field != FIELDS[0] and type(item) is not int:
            raise ValueError('Counter fields require integers')


def merge_usage(receiver, incoming):
    """Selected MergeWithRW behavior, not a complete boot/writeback transaction.

    The receiver's write count is retained. Native volume is a float64 and its
    stored 0.1-mL quantity is truncated on an increase; this projection reports
    the quantized value without producing any EEPROM bytes.
    """
    validate_usage(receiver)
    validate_usage(incoming)
    merged = {field: max(receiver[field], incoming[field]) for field in FIELDS[:3]}
    merged['WriteCount'] = receiver['WriteCount']
    return {'usage': merged,
            'quantized_volume_if_recomputed_100uL': int(merged[FIELDS[0]] * 10),
            'write_count_policy': 'retain_receiver_in_this_function',
            'scope': 'selected fields only; no other struct fields or stores modeled',
            'native_write_authorized': False}


def load_decision(a_valid, b_valid, a_blank=False, b_blank=False):
    """Model post-authentication selection for consumableTypeCartridge (4).

    Validity/blankness are assumed inputs, NOT verified evidence. Native
    initialization is reported but never implemented. Invalid records always
    block an owner write even where the vendor takes an initialization branch.
    """
    if any(type(v) is not bool for v in (a_valid, b_valid, a_blank, b_blank)):
        raise ValueError('Explicit boolean classification required')
    if (a_valid and a_blank) or (b_valid and b_blank):
        raise ValueError('Contradictory synthetic classification')
    if a_valid:
        selected, path = 'A', 'select_A'
    elif b_valid:
        selected, path = 'B', 'select_B'
    elif a_blank or b_blank:
        selected, path = None, 'native_initialization_path_not_reproduced'
    else:
        selected, path = None, 'native_error_recovery_path_not_reproduced'
    return {'selected_copy': selected, 'modeled_native_path': path,
            'write_count_used_for_selection': False,
            'assumed_successful_acquisition_and_authentication': True,
            'scope': 'selected Form 3 cartridge path, not full daemon startup',
            'owner_review': 'incomplete' if a_valid and b_valid else 'blocked_invalid_copy',
            'native_write_authorized': False, 'dispensing_authorized': False}


def demo():
    zero = dict(zip(FIELDS, (0.0, 0, 0, 0)))
    used = dict(zip(FIELDS, (800.0, 1200, 90, 100)))
    return {'data_class': 'SYNTHETIC', 'hardware_contact': False,
            'scenarios': {
                'zero_file_incoming_used_chip_receiver': merge_usage(used, zero),
                'zero_chip_receiver_used_file_incoming': merge_usage(zero, used),
                'both_valid_B_not_preferred_by_larger_counter': load_decision(True, True),
                'only_B_valid': load_decision(False, True),
                'both_invalid': load_decision(False, False),
                'invalid_and_blank': load_decision(False, False, a_blank=True)},
            'limitations': ['No cold-boot ordering or concurrency guarantee',
                            'No power-loss or restore test',
                            'No proof of physical remaining resin',
                            'No manufacturer network policy is applied']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', required=True, action='store_true',
                        help='Use authored hypothetical values only')
    parser.add_argument('--output', required=True, help='New local JSON report')
    args = parser.parse_args()
    write_json(args.output, demo())
    print(json.dumps({'data_class': 'SYNTHETIC', 'native_write_authorized': False}))


if __name__ == '__main__':
    main()
