# Scar Threshold

**How hard it has to rain before a burned canyon lets go.**

### [Open the map](https://scar-threshold.pages.dev/)

[![Scar Threshold, debris flow hazard for the 2024 Bridge Fire](web/screenshot.png)](https://scar-threshold.pages.dev/)

---

After a wildfire, a short burst of rain can turn a burned hillside into a fast slurry of mud and rock. It usually happens in the first winter, and often from a storm that would be unremarkable on unburned ground.

This pipeline takes satellite imagery, elevation and soil data for a burn scar, splits the terrain into drainage basins, and reports for each one the rainfall intensity that gives it a 50% chance of producing a debris flow. It has been run on two 2024 southern California fires, Bridge and Line: 408 basins, all from public data, running end to end in a browser from a single configuration block.

The model is not the contribution. USGS publishes both the equations and a reference implementation. What this project offers is the ingest, the validation and the delivery, plus an uncertainty analysis that operational assessments do not publish.

## Four results

**The implementation is exact.** Given identical inputs, this project's model matches `pfdf.models.staley2017`, the official USGS package, bit for bit across 1,422 forward evaluations and 237 inverse solves. It also reproduces the published USGS assessment for the Bridge Fire to floating point precision on all 703 pieces of burned ground. The comparison was then deliberately broken to confirm it was capable of failing.

**The disagreement with USGS is traceable.** On the Bridge Fire, the two assessments agree on where the hazard is: 99.8% of the ground USGS rates high is rated high here. They differ on magnitude by 7.7 mm/hr (area-weighted), and that gap decomposes into terrain, soil and burn severity, with each contribution measured. Delineation scale was tested across a 25-fold range and ruled out.

**It over-warns, and does not meaningfully under-warn.** Across six combinations of severity threshold and soil rule, the typical basin's threshold moves by about 2 mm/hr. Rerunning with the field-validated BAER soil burn severity map instead of satellite severity pushes basins outside that range in one direction only: toward less hazard. That happens in 87 of 237 basins on Bridge and 24 of 171 on Line. The only basin that moves the other way, on Line, does so by 0.4 mm/hr at a threshold of 66 mm/hr. On both fires, every basin the pipeline rates never-High is also not High when rerun with the BAER map.

**One notebook, any fire.** Everything fire-specific lives in one configuration block: the name, rough centre and acreage from the incident page, and two date windows. The notebook suggests the satellite scenes, runs through to the web map, and checks itself against earlier validated runs. Rerunning both fires through it reproduces the originals basin for basin, to floating point precision.

## The fires

| | Bridge | Line |
|---|---|---|
| Ignited | 8 September 2024 | 5 September 2024 |
| Size | 56,281 acres | 43,978 acres |
| Where | San Gabriel Mountains | San Bernardino Mountains |
| Basins | 237 | 171 |
| Moderate or high severity, satellite vs BAER | 76.5% vs 58% | 85% vs 71% |
| Median basin threshold | **16.4 mm/hr** | **19.0 mm/hr** |

The median threshold is the 15-minute rainfall that gives the typical basin a coin-flip chance of a debris flow. Neither number is a remarkable storm in southern California.

Satellite severity rates more ground badly burned than the BAER field teams do on both fires, which is why the pipeline runs conservative. The gap is larger on Bridge, which is mostly chaparral, than on Line, which burned a mix of grass, chaparral and timber. Two fires suggest a fuel effect; they do not prove one.

## What is here

```
src/debrisflow/                  the pipeline: severity, terrain, basins, soils, model, sensitivity
tests/                           184 tests
05_generalized_pipeline.ipynb    any fire, perimeter to web map, from one config block
00 to 04 .ipynb                  the original Bridge notebooks: ingest, USGS comparison, sensitivity
web/                             the map
```

Data sources: Sentinel-2 via the Planetary Computer, USGS 3DEP 10 m elevation, USDA STATSGO soils, CAL FIRE FRAP perimeters, USDA Forest Service BAER soil burn severity. No API keys, no paid services.

## Run it

```bash
pip install -r requirements.txt
python -m pytest -q          # 184 passed
```

Or open `00_model_driver.ipynb` in Colab, which clones this repository and runs everything. To run a fire, open `05_generalized_pipeline.ipynb`, fill in the configuration block at the top, and run it top to bottom. That takes considerably longer, since it reads satellite imagery and queries four external services.

## More

- **[METHODS.md](METHODS.md)** for the full method, every design decision, the validation in detail and the known limitations
- Staley, D.M. and others (2017), *Prediction of spatially explicit rainfall intensity-duration thresholds for post-fire debris-flow generation in the western United States*, Geomorphology 278, 149-162
- [USGS `pfdf`](https://code.usgs.gov/ghsc/lhp/pfdf), the authoritative implementation. This project's model is an independently tested reimplementation for cross-checking, not a replacement.
