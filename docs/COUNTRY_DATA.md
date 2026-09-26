# Offline country catalog

`core/countries.json` contains the 249 assigned ISO 3166-1 alpha-2 codes, alpha-3
search aliases and English / Simplified Chinese display names. It was generated
on 2026-09-27 using the code assignments in
[pycountry's iso-codes database](https://github.com/pycountry/pycountry/blob/main/src/pycountry/databases/iso3166-1.json)
and `Intl.DisplayNames` in Node 24.18.0 (ICU 78.3, CLDR 48.0, Unicode 17.0).
Only the code assignments are taken from iso-codes; localized display names are
Unicode CLDR data. The [Unicode license notice](UNICODE_LICENSE.txt) is included.
These are region display names, not a political or routing classification.

There is no runtime dependency on Node, pycountry, GeoIP or a network service.
`core/countries.py` adds flag emoji, existing group-label compatibility, curated
city/abbreviation aliases, common-first ordering and the separate Unknown entry.
The browser receives this exact mapping through Jinja JSON. Search uses the same
aliases plus the explicit `tai` search alias for Thailand. That search alias is
not an automatic country-detection hint.

To refresh data, review the 249 assignments from the linked source and generate
English / Chinese names with `new Intl.DisplayNames(['en'], {type:'region'})` and
`new Intl.DisplayNames(['zh-Hans'], {type:'region'})`. Record the runtime/CLDR
versions and review the resulting JSON diff; run country, parser, UI and YAML
regressions. Do not silently update data at application startup.

Detection is conservative: bounded Latin words, uppercase ISO/short codes,
Chinese phrases and flags. Specific phrases beat contained phrases (North Korea
versus Korea); separate conflicting hints produce Unknown. `LA` in an inferred
name means Los Angeles as requested; explicit `LA|name|URI`, Laos/老挝 or 🇱🇦 means
Laos. A name is only a hint and can always be corrected manually.
