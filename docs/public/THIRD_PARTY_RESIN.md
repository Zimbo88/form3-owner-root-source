# Third-party resin: reference print and reuse experience

## Reported result

**OWNER-REPORTED HARDWARE OBSERVATION — recorded 2026-10-09.**

> I completed a print with Anycubic High Clear resin using the normal
> Clear V4 profile (`FLGPCL04`), without Open Material Mode. I considered the
> finished print excellent. This made using the printer considerably cheaper
> for me.

The reference printer is a Form 3 running 2.5.6-2773. The cartridge and tank
reported Clear V4 for this experiment. That assignment selects an existing
printer profile; it does not turn the resin into Formlabs Clear V4.

This is a report of one successful print. No dimensional measurements, mechanical
property tests, exposure calibration series, long-term tank/valve testing or
independent comparison were supplied with the report. The project does not claim
that every Anycubic product, batch, geometry or other resin works with this profile.
No photograph or screenshot in the panel guide is evidence of this print unless
explicitly identified as such.

## Cartridge cleaning: what I personally tried

> I reused a cartridge. I rinsed it twice using the same isopropyl alcohol,
> then once with fresh isopropyl alcohol, shaking it during the rinses. I used
> compressed air carefully to dry the inside before adding the other resin.
> I then reset the electronic usage and assigned the intended material to the
> cartridge and tank.

This paragraph preserves the owner's experience, **not a validated cleaning
procedure**. It does not establish that shaking, those rinse counts or compressed
air remove all resin/solvent, preserve the valve and plastics, or make reuse safe.
There is no recorded pressure, solvent concentration, drying measurement or
long-term leak result. Compressed air can disperse liquid resin/IPA and create
vapour or mist; this report is not a recommendation to blow solvent out of a
cartridge.

Formlabs specifically advises using IPA on cartridge identification contacts and
avoiding it on other cartridge parts. That differs from the experiment above.
The manufacturer's motive cannot be established from the successful print.
See [cartridge maintenance and storage](https://formlabs.com/support/Resin-cartridge-maintenance-and-storage/)
and [IPA handling](https://formlabs.com/support/Isopropyl-Alcohol-IPA/).
The resin supplier's [High Clear product information](https://store.anycubic.com/collections/uv-resin/products/high-clear-resin)
is not a certification for this Form 3 profile or for cleaning/reusing a cartridge.

## Electronic operations are separate

- **Usage adjustment** changes accounting. It neither fills a cartridge nor measures
  the physical volume. Preserve native lifetime/write-counter semantics and retain
  the original snapshot.
- **Material assignment** changes the reported profile identity. It is separate
  from usage reset and must preserve the consumable's physical identity and keys.
- **Tank assignment** uses a different format and native path from cartridge
  assignment. Cartridge support does not establish a safe general tank writer.
- **Backup** preserves evidence and recovery inputs. A backup alone does not prove
  that an arbitrary damaged EEPROM can be restored.

See [current consumable scope](CONSUMABLE_BACKUPS.md) and
[historical panel transaction scope](CARTRIDGE_PANEL_RESET.md). The accepted format and
firmware gates remain authoritative. Unknown formats are refused, not treated as
another supported cartridge.

## Open Material Mode

This particular reported print did not require OMM. It does not establish that
OMM is unnecessary for all materials or that a relabelled cartridge provides its
supported workflows. The project does not issue licenses or claim manufacturer
approval for third-party resin/profile combinations. The
[material and OMM research](MATERIAL_SETTINGS_RESEARCH.md) keeps these mechanisms
separate.

## Further useful evidence

Record the exact product/batch privately, print geometry category, layer height,
profile, wash/cure process, measured dimensions and repeat-print results. Compare
leakage, dispensing behaviour and tank/valve condition over time. Share sanitized
measurements rather than private job models or cartridge identities. A failed
repeat must remain visible alongside this successful report.
