# Post-Fire Debris Flow Hazard Pipeline

Predicting which burned canyons will produce debris flows, and how hard it has to rain to set them off.

**Status:** model layer complete and tested, soil ingest verified against the live USDA service. Satellite and elevation ingest not started.

---

## The problem

After a wildfire, soil becomes water-repellent and the vegetation that held it in place is gone. When a short, intense downpour hits a steep burned slope, the hillside mobilises into a fast-moving slurry of mud, rock and debris that runs down the canyon. Post-fire debris flows kill people and destroy infrastructure, often within the first winter after a fire, and often from storms that would be unremarkable on unburned ground.

They are also predictable. Steepness, burn severity, soil erodibility and rainfall intensity combine in a way that has been empirically modelled.

## What this project does

An automated pipeline that ingests Sentinel-2 imagery for a California burn scar, derives terrain and soil properties, scores every drainage basin using the USGS operational debris-flow models, and serves the result as an interactive web map.

The value here is not the model. USGS publishes both the equations and a reference implementation. The value is in the ingest, the validation, and the delivery: getting real satellite, elevation and soil data through a defensible pipeline and out to a map anyone can open.

## The model

This project implements the M1 likelihood model from Staley et al. (2017):

```
X = B + Ct·(T·R) + Cf·(F·R) + Cs·(S·R)
P = e^X / (1 + e^X)
```

| Term | Meaning | Source |
|---|---|---|
| **T** | Fraction of basin that is **both** ≥23° slope **and** burned at moderate/high severity | USGS 3DEP 10 m DEM + Sentinel-2 dNBR |
| **F** | Mean basin dNBR ÷ 1000 | Sentinel-2 L2A (B08, B12) |
| **S** | Area-weighted mean soil KF-factor | USDA STATSGO (SSURGO for sensitivity) |
| **R** | Rainfall accumulation in mm over 15 minutes | User-selected design storms |

Basins are classified Low (P < 0.2), Moderate (0.2 ≤ P < 0.6), High (P ≥ 0.6). The model is also inverted to report the rainfall intensity required to reach P = 0.5, which is the number operational warning systems actually use.

## Three ways this model is easy to get wrong

Each of these produces a plausible-looking but incorrect hazard map. Each is now pinned by a regression test.

**T is an intersection, not a product.** A basin can be 90% steep and 90% burned while the steep parts and the burned parts barely overlap. Computing `T = fraction_steep × fraction_burned` underestimated T by 38% on our test scene, because steepness and severity are spatially correlated in real burn scars.

**R is an accumulation, not an intensity.** The M1 rainfall term is millimetres accumulated over the duration, not mm/hr. Over 15 minutes these differ by 4x. Note that the companion Gartner (2014) volume model expects intensities, so a full pipeline carries both conventions at once. `likelihood()` therefore requires an explicit convention argument with no default.

**Null soil values must be dropped, not zeroed.** Rock outcrop and water have no KF-factor. Treating those as 0.0 rather than excluding them and renormalising gave S = 0.140 instead of 0.350 on a partially-covered basin, a 2.5x error in a predictor that alone can move a basin from Moderate to High.

## Repository layout

```
src/debrisflow/
    m1.py          M1 likelihood model, forward and inverted
    severity.py    NBR, dNBR, offset corrections -> the F variable
    terrain.py     Horn slope, pysheds delineation -> the T variable
    soils.py       KF-factor aggregation, Soil Data Access -> the S variable
    _compat.py     numpy 2 shim for pysheds
tests/             92 tests
00_model_driver.ipynb        Colab driver: pulls this repo, runs it, shows results
01_bridge_fire_ingest.ipynb  Colab driver: real data ingest for the 2024 Bridge Fire
```

Each module separates **pure array math** from **network IO**. That split is what makes a pipeline with remote data dependencies unit-testable: the notebook fetches, the tested functions compute.

## Design decisions

**Own basin delineation, not NHDPlus catchments.** M1 was calibrated on watersheds of roughly 0.1 to 8 km². Larger basins average severity and steepness over terrain that never contributes sediment, diluting T and under-predicting hazard. Basins are delineated with pysheds from the 10 m DEM, and any basin outside the calibration range is flagged as an extrapolation rather than presented with equal confidence.

**10 m DEM, not coarser.** Slope statistics are resolution dependent. A plane that reads 45° at 10 m reads 18.4° at 30 m and 6.3° at 90 m. Since M1's threshold is 23°, a coarse DEM silently erases the steep pixels the model depends on.

**Burn severity is computed at 20 m, not resampled up to 10 m.** NBR needs B08 (10 m) and B12 (20 m) on a shared grid, and the two directions are not equivalent: averaging B08 down to 20 m discards detail that was really measured, while interpolating B12 up to 10 m fabricates detail that was not. This pipeline takes the first option and computes dNBR natively at 20 m. Where T requires severity on the 10 m terrain grid, the 20 m severity raster is expanded by nearest neighbour, which replicates a real measurement across the four cells it covers rather than inventing intermediate values.

**STATSGO primary, SSURGO as a sensitivity axis.** USGS operational assessments use STATSGO, and M1's coefficients were fitted against it. Using STATSGO for headline numbers keeps cross-validation against published assessments apples-to-apples. SSURGO is finer and genuinely better data, so it runs as a second pass and becomes a documented sensitivity result rather than an unexplained deviation.

**KF, not KW.** `kwfact` is the rock-free variant; Staley uses the whole-soil `kffact`. A test fails if these are ever swapped.

**Surface horizon only.** Post-fire rilling and dry ravel act on the surface, so deeper soil horizons are irrelevant to the initiation process being modelled.

## Testing

```bash
python -m pytest -q          # 92 passed
```

A wrong hazard map is visually indistinguishable from a correct one, so correctness here cannot be established by inspection. Slope is verified against planes whose angle is known analytically. The rainfall unit error, the T intersection error and the soil null-handling error each have a test that fails if reintroduced. `test_compat.py` runs real D8 flow accumulation on a generated GeoTIFF, so if pysheds ever ships a numpy 2 compatible release, deleting the shim is immediately safe or immediately not.

## Known limitations

- **No imagery or elevation data yet.** Burn severity and terrain have been verified against synthetic scenes only. Soil is verified against live STATSGO output.
- **No cross-validation against the official USGS `pfdf` package.** Planned, and the strongest validation artifact available for this project.
- **Likelihood only.** The Gartner (2014) volume model and combined hazard classification are not implemented.

## Roadmap

1. ~~Verify Soil Data Access connectivity and schema~~ **done.** Live STATSGO output is captured as a regression fixture in tests/test_soils_sda.py.
2. Real data ingest: pre/post Sentinel-2 and 3DEP DEM for the 2024 Bridge Fire (San Gabriel Mountains)
3. Cross-validate basin probabilities against the official USGS `pfdf` implementation
4. Sensitivity analysis: which basins are High under *every* assumption, and which flip depending on dNBR threshold, basin delineation and soil dataset. USGS publishes single-scenario assessments without uncertainty bounds, so this is the piece that is genuinely additional.
5. Delivery: tippecanoe to PMTiles, COGs, Cloudflare R2, MapLibre GL JS frontend

## References and attribution

- Staley, D.M., Negri, J.A., Kean, J.W., Laber, J.L., Tillery, A.C., Youberg, A.M. (2017). Prediction of spatially explicit rainfall intensity-duration thresholds for post-fire debris-flow generation in the western United States. *Geomorphology*.
- USGS `pfdf` package, the authoritative implementation of these models. This project's `m1.py` is a transparent, independently tested reimplementation intended for cross-checking, not as a replacement.
- Sentinel-2 L2A via the Planetary Computer STAC catalogue; USGS 3DEP elevation; USDA NRCS Soil Data Access.

## Setup

```bash
pip install -r requirements.txt
python -m pytest -q
```

Or open `00_model_driver.ipynb` in Colab, which clones this repository and runs everything.
