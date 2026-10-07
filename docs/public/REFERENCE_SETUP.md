# Reference setup and required equipment

This table distinguishes retained observations from build requirements. It is not
a shopping-list guarantee or a compatibility expansion. See [Evidence status](EVIDENCE_STATUS.md).

| Item | Retained reference / requirement | Proof and unresolved detail |
|---|---|---|
| Printer | Formlabs Form 3 / Daguerre; selected p6, 2.5.6-2773 | Acquisition and later [panel receipt](../../analysis/owner/cartridge-panel-0.5.13.json); other board revisions not established |
| Storage | QSPI 4,194,304 bytes; eMMC user area 15,678,308,352 bytes | Exact layout gates in ownerctl; unknown hash/layout stops |
| Flash identity | Historical flashrom selection `W25Q32JV` | **Not** complete suffix/package/voltage identification; readable full marking and actual rail/auxiliary-pin checks required |
| Programmer host | Raspberry Pi 5, Raspberry Pi OS Lite 64-bit | [Historical kit provenance](PI5_CLIP_GUIDE.md); exact OS release/kernel and flashrom version not reliably retained in this public evidence |
| SPI | Historical `/dev/spidev0.0`, SPI0, 500 kHz | Recorded setup, not an automatic default for an unknown board. Pinned flashrom documentation is a reference version, **not** the measured programmer version |
| Clip and leads | SOIC clip matching the identified package, short individually continuity-checked leads | No approved universal clip model/wire-color map. Still-soldered chip; SOM was removed, no soldered UART in this reference method |
| Electrical tools | Multimeter, stable nonconductive/ESD-appropriate work surface | [Measurement table](PI5_CLIP_GUIDE.md); continuity/resistance only fully unpowered, DC voltage for residual/rail checks. No universal safe resistance threshold |
| Laptop | Linux host; current Python 3.12+ for development checks | [Build dependencies](BUILD.md); Ubuntu used historically, exact distribution release not pinned as a compatibility guarantee |
| Target runtime | ARMv7/armhf, Linux 4.9.65+, Python 3.5.3, glibc 2.26, OpenSSL 1.0.2o, OpenSSH 7.5p1 | Device-derived hash manifest and historical target observations; no runtime upgrade supplied |
| Rescue build | BusyBox 1.37.0, Bootlin ARMv7 musl stable-2024.05-1 | [Source lock](../../rescue/sources.lock.json), GCC 13.3.0, binutils 2.41, musl 1.2.5; not the normal OS runtime |
| Storage/network | Space for full protected originals, failed acquisitions, independent backup and private build outputs; isolated service Ethernet | Pi streams to laptop; no assumption of a 16 GB image fitting Pi storage. Isolate saved WLAN/IPv6/USB/relays before normal boot |

**STOP CONDITION:** incomplete chip suffix, unresolved shared-rail behavior,
inconsistent reads, unknown profile hash, missing independent backup or an
unreviewed filesystem recovery state. “Likely compatible” is not reference-tested.
Do not replace a hash/voltage gate with this table.

For a new compatibility report, manually provide only repository commit/version,
public firmware build name, publicly documented model/revision (without serial),
tool versions, sizes and named gate results. Include a hash only after deciding
that the corresponding artifact/fingerprint may be shared. Do not attach raw
QSPI environment, dumps, full preflight JSON, CID/MAC/serials, logs or screenshots
with identifiers. The [hardware report template](../../.github/ISSUE_TEMPLATE/compatibility.md)
uses this allowlist; there is deliberately no automatic device-data uploader.
