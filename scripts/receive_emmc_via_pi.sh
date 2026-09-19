#!/usr/bin/env bash
# Run manually ON THE LAPTOP. The Pi stores no image bytes on disk.
set -euo pipefail
umask 077
usage() {
    echo 'Set FORM3_PI_SSH to an already trusted SSH config alias or user@host.' >&2
    echo 'Usage: receive_emmc_via_pi.sh NAME.img EXPECTED_BYTES [SOURCE_SHA256]' >&2
    echo 'Example: receive_emmc_via_pi.sh form3-mmcblk0-YYYYMMDD.img <exact blockdev --getsize64 result>' >&2
    exit 2
}
[[ $# -ge 2 && $# -le 3 ]] || usage
pi_target=${FORM3_PI_SSH:?set an already trusted Pi SSH alias or user@host}
[[ $pi_target =~ ^[A-Za-z0-9][A-Za-z0-9._@:-]*$ ]] || usage
name=$1; expected=$2; source_hash=${3:-}
[[ $name =~ ^[A-Za-z0-9][A-Za-z0-9._-]*\.img$ ]] || usage
[[ $expected =~ ^[1-9][0-9]{0,17}$ ]] || usage
[[ -z $source_hash || $source_hash =~ ^[a-fA-F0-9]{64}$ ]] || usage
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
outdir=$root/hardware/emmc/original
mkdir -p -- "$outdir"
output=$outdir/$name
for suffix in '' .sha256 .incomplete .receipt.txt; do
    [[ ! -e $output$suffix && ! -L $output$suffix ]] || { echo "Refusing existing path: $output$suffix" >&2; exit 1; }
done
available=$(df -PB1 -- "$outdir" | awk 'NR==2 {print $4}')
(( available > expected + 1073741824 )) || { echo 'Insufficient free space (requires expected bytes plus 1 GiB).' >&2; exit 1; }
# Strict host verification prevents silently trusting a new or changed SSH host.
remote=(ssh -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=10
        -o ServerAliveInterval=15 -o ServerAliveCountMax=3 "$pi_target")
set -o noclobber
printf 'INCOMPLETE until length and receiver hash are recorded. Expected bytes: %s\n' "$expected" > "$output.incomplete"
# The remote command probes help locally on the Pi and binds only the isolated IP.
# Unrecognised nc variants are rejected. Never run a second listener as fallback.
remote_script=$(cat <<'REMOTE'
set -eu
command -v ip >/dev/null
ip -4 -o addr show dev eth0 | grep -q ' inet 10\.0\.0\.1/24 ' || { echo 'Pi eth0 is not 10.0.0.1/24' >&2; exit 1; }
command -v nc >/dev/null || { echo 'Install netcat-openbsd on the Pi manually first.' >&2; exit 1; }
help=$(nc -h 2>&1 || true)
case "$help" in
    *OpenBSD*) set -- nc -4 -l 10.0.0.1 9000 ;;
    *'v1.10'*) set -- nc -l -s 10.0.0.1 -p 9000 ;;
    *) echo 'Unsupported netcat; use netcat-openbsd. No listener started.' >&2; exit 1 ;;
esac
echo 'Starting Pi listener on 10.0.0.1:9000. Start form3-backup from the rescue shell.' >&2
# Empty stdin is separate from the SSH script. stdout consists only of image data.
exec "$@" </dev/null
REMOTE
)
echo "Receiving to $output; interrupted or short images remain marked INCOMPLETE." >&2
receive_ok=1
if command -v pv >/dev/null; then
    if ! "${remote[@]}" bash -s <<< "$remote_script" | pv -s "$expected" > "$output"; then
        echo 'Reception failed. Hashing/preserving partial bytes; use a NEW filename for retry.' >&2; receive_ok=0
    fi
else
    if ! "${remote[@]}" bash -s <<< "$remote_script" > "$output"; then
        echo 'Reception failed. Hashing/preserving partial bytes; use a NEW filename for retry.' >&2; receive_ok=0
    fi
fi
actual=$(stat -c %s -- "$output")
# Hash both interrupted and cleanly terminated short streams; never discard partial bytes.
(cd -- "$outdir" && sha256sum -- "$name") > "$output.sha256"
read -r receiver_hash ignored < "$output.sha256"
printf 'Expected bytes: %s\nReceived bytes: %s\nReceiver SHA256: %s\nSource SHA256: %s\nPipeline completed: %s\n' \
    "$expected" "$actual" "$receiver_hash" "${source_hash:-PENDING MANUAL COMPARISON}" "$receive_ok" > "$output.receipt.txt"
(( receive_ok == 1 )) || { echo 'INCOMPLETE: transfer failed; partial hash and receipt preserved.' >&2; exit 1; }
[[ $actual == "$expected" ]] || { echo "INCOMPLETE: received $actual of $expected bytes." >&2; exit 1; }
if [[ -n $source_hash && ${source_hash,,} != "$receiver_hash" ]]; then
    echo 'HASH MISMATCH. Preserve this image for investigation.' >&2; exit 1
fi
rm -- "$output.incomplete"
cat -- "$output.receipt.txt"
echo 'Compare the source stream SHA256 printed on the printer with this receiver SHA256.'
echo 'Correct byte count alone does not prove a valid backup.'
