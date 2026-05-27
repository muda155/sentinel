# World Monitor Archive (R5 — Risk Mitigation)

This directory exists per spec **Risk R5**: preserve World Monitor reference documentation in case the live site becomes unavailable.

The World Monitor methodology documents describe the "Geographic Convergence Detection" and "Attributed AI Briefs" approaches that Sentinel's scoring and LLM verification systems are based on.

## URLs to Archive

| Document | URL |
|----------|-----|
| Geographic Convergence | https://www.worldmonitor.app/docs/geographic-convergence |
| Algorithms | https://www.worldmonitor.app/docs/algorithms |
| Data Sources | https://www.worldmonitor.app/docs/data-sources |

## How to Archive

When internet access is available, download each page for offline preservation:

**Option A — wget (recommended):**
```bash
wget -p -k -P docs/world_monitor_archive/ \
  https://www.worldmonitor.app/docs/geographic-convergence \
  https://www.worldmonitor.app/docs/algorithms \
  https://www.worldmonitor.app/docs/data-sources
```

**Option B — Browser:**
Open each URL and use File > Save Page As > "Web Page, Complete".

After downloading, commit the HTML files and associated assets to version control.

## Archive Status

- **Last archive attempt:** Not yet performed (no internet access during Phase F hardening)
- **Placeholder file:** This README serves as documentation until the actual HTML archives are downloaded
