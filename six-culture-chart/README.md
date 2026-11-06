# Six-culture verified chart

Outputs: `BIRTH_INPUT.json`, `INPUT_AUDIT.md`, `CALCULATION_MANIFEST.json`, `MASTER_DATASET.json/.md`,
`VERIFICATION_REPORT.json/.md`, `SYNTHESIS.json`, `FINAL_READING.md`.

## Reproduce

```bash
python3 -m venv venv && . venv/bin/activate && pip install -r requirements.lock.txt
mkdir ephe && for f in sepl_18.se1 semo_18.se1 seas_18.se1; do curl -sSfLo ephe/$f https://raw.githubusercontent.com/aloistr/swisseph/master/ephe/$f; done
mkdir jpl && curl -sSfLo jpl/de421.bsp https://raw.githubusercontent.com/skyfielders/python-skyfield/master/ci/de421.bsp
mkdir js && (cd js && npm init -y && npm i iztro@2.5.0)
cp BIRTH_INPUT.example.json BIRTH_INPUT.json   # then edit with real data
python build_dataset.py . ephe jpl/de421.bsp js
python synthesize.py .
python render_reports.py .
```

Personal input and outputs are git-ignored. Note: synthesize.py currently assumes the as-of date 2026-11-06 and male gender for Zi Wei.

Personal input and all chart outputs are git-ignored and stay local.

Checksums of the ephemeris files and the builder are in `CALCULATION_MANIFEST.json`. `FINAL_READING.md` is hand-written from `SYNTHESIS.json`.
