#!/usr/bin/env bash
# Run manually ON THE PI after review. No SSH is performed by this script.
set -euo pipefail
[[ ${1:-} == --apply && $# == 1 ]] || { echo 'Usage (on Pi): sudo bash pi_rescue_link_setup.sh --apply' >&2; exit 2; }
[[ $EUID == 0 ]] || { echo 'Run as root on the Pi.' >&2; exit 1; }
[[ -d /sys/class/net/eth0 ]] || { echo 'eth0 is absent.' >&2; exit 1; }
[[ ! -e /sys/class/net/eth0/master ]] || { echo 'Refusing: eth0 belongs to a bridge/bond; review manually.' >&2; exit 1; }
# Release eth0 alone from NetworkManager. Leave wlan0 and its routes untouched.
if command -v nmcli >/dev/null && nmcli general status >/dev/null 2>&1; then
    nmcli device set eth0 managed no
fi
# Refuse if another network manager could race these ephemeral settings.
if command -v systemctl >/dev/null && { systemctl is-active --quiet dhcpcd || systemctl is-active --quiet systemd-networkd; }; then
    echo 'Review the active network manager and exclude eth0 manually, then rerun.' >&2
    exit 1
fi
ip link set eth0 up
ip -4 addr flush dev eth0
ip -4 route flush dev eth0
ip addr add 10.0.0.1/24 dev eth0
sysctl -q -w net.ipv4.conf.eth0.forwarding=0
if [[ -e /proc/sys/net/ipv6/conf/eth0/disable_ipv6 ]]; then
    sysctl -q -w net.ipv6.conf.eth0.disable_ipv6=1
fi
ip -4 addr show dev eth0
ip -4 route show dev eth0
echo 'eth0 configured for isolated rescue. wlan0 configuration was not changed.'
echo 'No NAT, bridge, DHCP server or forwarding was enabled.'
