# Post-Fire Debris Flow Hazard Pipeline

Working out which burned canyons will produce debris flows, and how hard it has to rain to set them off.

**Status:** complete pipeline, run end to end on the 2024 Bridge Fire. Model implementation cross-validated against the official USGS package. 150 tests passing.

---

## The problem

After a wildfire, two things happen to a hillside. The plants that held the soil in place are gone, and the soil itself often turns water repellent, because burned organic matter leaves a waxy layer near the surface. Rain that would normally soak in runs straight off instead.

When a short, intense burst of rain hits a steep burned slope, the loose material on that slope starts moving. It picks up more material as it goes, and what reaches the canyon bottom is a fast slurry of mud, rock and burned vegetation. That is a debris flow. They kill people and destroy infrastructure, usually in the first winter after a fire, and usually from storms that would be completely unremarkable on unburned ground.

The useful part is that they are predictable. Four things control whether a given canyon produces one: how steep it is, how badly it burned, how erodible the soil is, and how hard it rains. Staley et al. (2017) fitted those four things to a database of real post-fire debris flows and produced a model that works well enough to run operational warning systems in the western United States.

## What this project does

It is a pipeline. Satellite imagery, elevation data and soil data go in at one end, and a hazard rating for every small drainage basin comes out the other.

Concretely, for a burned area it will:

1. Fetch the official fire perimeter
2. Find cloud free Sentinel-2 scenes from before and after the fire
3. Compute a burn severity map from those scenes
4. Fetch a 10 m elevation model and compute slope
5. Work out which way water flows and split the terrain into drainage basins
6. Query the USDA soil database for erodibility
7. Score every basin with the USGS debris flow model
8. Report, for each basin, the rainfall intensity that gives it a 50/50 chance of producing a debris flow

**The honest framing.** The model is not the contribution. USGS publishes both the equations and a reference Python implementation called `pfdf`. What this project offers is the ingest, the validation and the delivery: real satellite, elevation and soil data through a pipeline where every choice is written down and every failure mode is documented, plus a sensitivity analysis that USGS does not publish.

## Results: the 2024 Bridge Fire

The Bridge Fire burned about 56,000 acres of the San Gabriel Mountains northeast of Los Angeles, starting on 8 September 2024. It was chosen because it has extreme topography, dense high severity burn, real downstream exposure at Wrightwood and along the canyon corridors, and a published USGS assessment to compare against later.

**Inputs**

| | Value |
|---|---|
| Perimeter | CAL FIRE FRAP, 56,281 acres, 226.6 km² |
| Pre-fire scene | Sentinel-2B, 20 August 2024, no cloud over the burn |
| Post-fire scene | Sentinel-2B, 29 September 2024, no cloud over the burn |
| dNBR offset correction | -5.05, from 484,963 unburned pixels |
| Elevation | USGS 3DEP 10 m, 196 m to 3,068 m |
| Soil | USDA STATSGO, 10 map units, KF 0.242 to 0.339 |

**What the terrain and imagery say**

- 76.5% of the burn area is moderate or high severity
- 83.0% of the burn area is 23 degrees or steeper
- Mean slope across the whole extent is 22.5 degrees

**Basins**

237 drainage basins touching the fire, median size 0.38 km², all inside the model's calibration range. Together they cover 87.6% of the burn area. The missing 12.4% is trunk canyon floors that are too large to be treated as source basins at this scale.

**Hazard**

| Rainfall (15 min) | Basins at High likelihood |
|---|---|
| 12 mm/hr | 0.0% |
| 16 mm/hr | 24.1% |
| 20 mm/hr | 54.4% |
| 24 mm/hr | 63.7% |
| 32 mm/hr | 70.9% |
| 40 mm/hr | 75.1% |

Median basin needs **16.4 mm/hr** of 15 minute rainfall to reach a 50% chance of a debris flow. The range across basins runs from 11.4 to 84.5 mm/hr. Low numbers mean dangerous: those basins need very little rain.

For context, 16 mm/hr over 15 minutes is not a remarkable storm in southern California. It is the kind of short burst an ordinary winter atmospheric river delivers.

## The model

The M1 likelihood model from Staley and others (2017):

```
X = B + Ct·(T·R) + Cf·(F·R) + Cs·(S·R)
P = e^X / (1 + e^X)
```

This is a logistic regression. The first line adds up four weighted terms to get a score, and the second line squashes that score onto a 0 to 1 scale so it can be read as a probability.

| Term | What it means, plainly | Where it comes from |
|---|---|---|
| **T** | The fraction of the basin that is steep **and** badly burned, at the same time | 3DEP 10 m DEM + Sentinel-2 dNBR |
| **F** | How badly the basin burned on average | Sentinel-2 (bands B08 and B12) |
| **S** | How easily the soil washes away | USDA STATSGO |
| **R** | How much rain falls, in mm, over 15 minutes | You choose the design storm |
| **B, Ct, Cf, Cs** | Fitted constants from the paper | -3.63, 0.41, 0.67, 0.70 |

Basins are classed Low (P below 0.2), Moderate (0.2 to 0.6) and High (0.6 and above). The model is also run backwards to answer the more useful question: how much rain does this basin need to reach a 50% chance? That is the number warning systems actually use, because a forecaster can compare it directly against a predicted storm.

## Three ways this model is easy to get wrong

Each of these produces a hazard map that looks completely normal and is wrong. Each now has a test that fails if it comes back.

**T is an intersection, not a product.** A basin can be 90% steep and 90% burned while the steep parts and the burned parts barely overlap. Multiplying the two fractions together underestimated T by 38% on our test scene, because in real burn scars steepness and severity tend to occur in the same places. What the model cares about is where they coincide, since that is where loose material actually gets delivered to the channel.

**R is an accumulation, not an intensity.** The rainfall term is millimetres accumulated over the duration, not millimetres per hour. Over 15 minutes those differ by a factor of 4. To make this impossible to get wrong silently, `likelihood()` requires the caller to state which convention they are using and has no default. The companion Gartner (2014) volume model expects intensities instead, so a complete pipeline has to carry both conventions at once.

**Null soil values must be dropped, not zeroed.** Rock outcrop and open water genuinely have no erodibility factor. Treating those as 0.0 rather than excluding them and renormalising gave S = 0.140 instead of 0.350 on a partly covered basin. That is a 2.5x error in a predictor that on its own can move a basin from Moderate to High.

## What has been validated, and what has not

This distinction matters and is easy to blur, so it is stated explicitly.

**Validated.** Given identical T, F, S and R values, this project's `m1.py` produces bit for bit identical results to `pfdf.models.staley2017`, the official USGS implementation. That was checked across 1,422 forward evaluations (237 basins at 6 design storms) and 237 inverse solves. Maximum absolute difference: 0.000e+00.

The comparison was then deliberately broken to confirm it is capable of failing. Swapping two coefficients moves the result by 1.3e-01, passing intensity where accumulation was expected moves it by 8.3e-01, and perturbing a single coefficient by 1% moves it by 4.0e-03. So the exact agreement is a real result, not a comparison that always returns zero.

The captured values are frozen in `tests/test_m1_pfdf.py`, so the agreement holds as an ordinary regression test with no network access and no pfdf installed.

**Not validated.** Whether this pipeline's T, F and S match what pfdf's own ingest would produce from the same rasters. The burn severity, slope, flow routing and basin delineation steps have not been compared against `pfdf.severity`, `pfdf.watershed` or `pfdf.segments`.

In short: **the model implementation is verified, the ingest is not.** Those are different claims. Comparing against the published USGS Bridge Fire assessment is the pipeline level check, and it is on the roadmap rather than done.

## How it actually works, step by step

**Burn severity from two satellite pictures.** Healthy vegetation reflects near infrared light strongly and shortwave infrared weakly. Burned ground does the opposite. The Normalised Burn Ratio combines those two bands into a single number, and subtracting the after picture from the before picture gives dNBR, which is a map of how much changed.

Two pictures taken 40 days apart also differ for boring reasons: sun angle, atmosphere, slight seasonal change. So the pipeline looks at unburned land in a ring around the fire, where the answer should be zero, and measures what it actually says. Whatever that is, is the bias, and it gets subtracted from everything. On the Bridge Fire it came out at -5.05, which is tiny, mostly because both scenes came from the same satellite in the same dry season.

**Slope from an elevation model.** Slope is computed with Horn's method, the same 3x3 kernel that GDAL and ArcGIS use, so the numbers are comparable to standard GIS output.

**Flow routing needs the DEM repaired first.** Water flows to the lowest neighbouring cell. That breaks down when a cell has no lower neighbour, which happens constantly in real elevation data: small pits from measurement noise, and genuine closed depressions. Water routed into a pit has nowhere to go, and the flow network dies there, splitting one real canyon into several fake ones.

So three steps run before routing. Fill the pits. Resolve the flats that filling creates, since a perfectly flat cell has no lowest neighbour either. Then assign every cell a direction to its steepest neighbour and count how many cells drain through each point.

On the Bridge Fire, 0.79% of cells were altered by filling. The deepest fill was 74.7 m, which turned out to be San Gabriel Reservoir. A reservoir is a real closed depression and filling it seemed the correct course of action here.

**Slope comes from the raw DEM, routing from the repaired one.** This is worth stating clearly because it is easy to get backwards. Filling deliberately changes elevations, which is right for routing and wrong for measurement. Computing slope on the filled surface would report gradients invented by the fill algorithm.

**Basins.** Every cell that drains to the same outlet is one basin. Choosing the outlets is the hard part, because every cell along a stream is a candidate and they are all nested inside each other. The rule used here is: take the largest candidate whose contributing area is inside the model's calibration range, give it everything upstream, and repeat with what is left.

That is implemented as a single pass over cells sorted by contributing area rather than as one catchment trace per candidate. Because a cell's downstream neighbour always has more contributing area than the cell itself, it has already been decided by the time we reach the cell, so each cell simply inherits its downstream neighbour's basin. Same answer as the obvious approach, but it finishes.

**Soil.** The USDA Soil Data Access service is queried for the map units covering the basins, then for the surface horizon erodibility of each. Rolling that up takes three weighted averages: horizons to component, components to map unit, map units to basin. Each one drops missing values and renormalises rather than treating them as zero.

## Repository layout

```
src/debrisflow/
    m1.py          M1 likelihood model, forward and inverted
    severity.py    NBR, dNBR, offset corrections, gives F
    terrain.py     Horn slope, conditioning, D8 routing, gives T
    basins.py      D8 catchment traversal and basin delineation
    soils.py       KF-factor aggregation, Soil Data Access, gives S
    _compat.py     numpy 2 shim for pysheds
tests/             150 tests across 8 files
00_model_driver.ipynb        Colab driver: pulls this repo, runs it, shows results
01_bridge_fire_ingest.ipynb  Colab driver: full ingest for the 2024 Bridge Fire
```

Every module keeps **pure array maths** separate from **network calls**. The notebooks fetch, the tested functions compute. That split is what makes a pipeline with remote data dependencies testable at all: you cannot unit test a function that phones the internet, but you can unit test the function it hands its results to.

## Design decisions

**Own basin delineation, not NHDPlus catchments.** M1 was fitted on watersheds of roughly 0.1 to 8 km². Bigger basins average severity and steepness over ground that never contributes sediment, which dilutes T and under-predicts hazard. Basins outside that range are flagged as extrapolations rather than presented with equal confidence.

**10 m DEM, not coarser.** Slope depends on resolution. A plane reading 45 degrees at 10 m reads 18.4 degrees at 30 m and 6.3 degrees at 90 m. The model's threshold is 23 degrees, so a coarse DEM silently erases exactly the pixels it depends on.

**Burn severity computed at 20 m, not resampled up to 10 m.** NBR needs B08 at 10 m and B12 at 20 m on a shared grid, and the two directions are not equivalent. Averaging B08 down to 20 m discards detail that was really measured. Interpolating B12 up to 10 m invents detail that was not. This pipeline takes the first option. Where the terrain grid needs severity at 10 m, the 20 m values are replicated into their four cells, which repeats a real measurement rather than inventing intermediate values. The grids are deliberately snapped so this is exact.

**STATSGO first, SSURGO as a sensitivity axis.** USGS operational assessments use STATSGO and M1's coefficients were fitted against it, so using it keeps any comparison with published assessments like for like. SSURGO is finer and genuinely better data, so it runs as a second pass and becomes a documented sensitivity result rather than an unexplained deviation.

Note that the STATSGO spatial data lives in the `gsmmupolygon` table. The convenient SDA helper functions filter STATSGO out and return SSURGO, which would run without error and quietly break this decision.

**KF, not KW.** `kwfact` is the rock free variant. Staley uses whole soil `kffact`. A test fails if these are ever swapped.

**Surface horizon only.** Post-fire rilling and dry ravel act on the surface, so deeper horizons are irrelevant to the process being modelled.

**F is clamped at zero.** A negative basin mean dNBR means the basin looked slightly greener after the fire than before, which for basins that barely clip the perimeter is scene noise rather than negative burning. The model's fire term is a magnitude whose floor is "no burn". On the Bridge Fire this affected 19 of 237 basins, all with T below 0.02. The clamp happens in the driver and the raw value is kept alongside it, so it is visible in the output. The validation in `m1.py` was left strict.

## Testing

```bash
python -m pytest -q          # 150 passed
```

A wrong hazard map looks exactly like a correct one, so correctness here cannot be established by looking at it. The tests are built around that.

Slope is checked against planes whose angle is known from trigonometry. The three classic errors above each have a test that fails if reintroduced. `test_compat.py` runs real D8 flow accumulation on a generated GeoTIFF, so if pysheds ever ships a numpy 2 compatible release, deleting the shim is either immediately safe or immediately not.

Basin delineation is tested on synthetic flow grids small enough to verify by hand: a 3x3 where all eight neighbours drain to the centre catches a mis-encoded direction map, which would otherwise produce basins that drain the wrong way and look perfectly normal. There is also a property test on random grids checking that every labelled cell reaches its own basin's outlet before any other, a determinism test because greedy algorithms with tied sort keys silently reorder, and a cross-check against `pysheds.Grid.catchment` on a real DEM.

The model tests are described under validation above.

## Known limitations

**Vegetation change is not soil burn severity.** The 270 dNBR threshold used here classifies moderate and high severity from vegetation change. M1 was calibrated against soil burn severity, which USGS maps with BAER field teams. The two correlate but are not the same, and in chaparral they diverge in a known direction: the shrubs burn completely, giving very high dNBR, while the soil underneath may only be moderately affected. The 76.5% figure reported above is therefore plausibly higher than a soil burn severity map would give. Running the threshold at 200, 270 and 350 is the planned sensitivity axis.

**Basins cover 87.6% of the burn area, not all of it.** Trunk canyons with more than 8 km² of contributing area are outside the model's calibration range and cannot serve as source basins. Those unassigned valley floors are exactly where debris flows travel and where damage occurs, so the map describes where flows initiate rather than where they end up.

**S barely varies.** STATSGO map units are 1 to 10 km² against a median basin of 0.38 km², so most basins sit inside a single map unit. Across the entire Bridge Fire, S spans 0.242 to 0.339. Its coefficient is the largest in the model, but with that little spread it acts closer to a constant offset than a discriminator. Almost all the between-basin variation in the results comes from T. The SSURGO pass exists to quantify whether finer soil data changes that.

**The ingest is not cross-validated.** See the validation section. Only the model implementation has been checked against pfdf.

**Likelihood only.** The Gartner (2014) volume model and the combined hazard classification are not implemented, so this says how likely a debris flow is, not how big.

**Single fire, single scene pair.** Everything here has been run on one fire with one pre and post scene. Scene choice is a sensitivity axis that has not been exercised.

## Roadmap

1. ~~Verify Soil Data Access connectivity and schema~~ **done**, live STATSGO output captured as a fixture
2. ~~Real data ingest: Sentinel-2 and 3DEP for the 2024 Bridge Fire~~ **done**
3. ~~Cross-validate the model against the official USGS `pfdf` package~~ **done**, exact agreement, pinned as a test
4. Sensitivity analysis: which basins are High under *every* assumption, and which flip depending on dNBR threshold, basin delineation and soil dataset. USGS publishes single scenario assessments without uncertainty bounds, so this is the genuinely additional piece
5. Compare against the published USGS Bridge Fire assessment, which is the pipeline level validation the model comparison does not provide
6. Delivery: tippecanoe to PMTiles, COGs on Cloudflare R2, MapLibre GL JS front end

## References and attribution

- Staley, D.M., Negri, J.A., Kean, J.W., Laber, J.L., Tillery, A.C., Youberg, A.M. (2017). Prediction of spatially explicit rainfall intensity-duration thresholds for post-fire debris-flow generation in the western United States. *Geomorphology*, 278, 149-162.
- Gartner, J.E., Cannon, S.H., Santi, P.M. (2014). Empirical models for predicting volumes of sediment deposited by debris flows and sediment-laden floods in the transverse ranges of southern California. *Engineering Geology*, 176, 45-56.
- King, J.M. USGS `pfdf` package, the authoritative implementation of these models. This project's `m1.py` is a transparent, independently tested reimplementation intended for cross-checking, not as a replacement. https://code.usgs.gov/ghsc/lhp/pfdf
- Sentinel-2 L2A via the Microsoft Planetary Computer STAC catalogue
- USGS 3DEP 1/3 arc-second elevation
- USDA NRCS Soil Data Access, STATSGO2
- CAL FIRE FRAP historic fire perimeters

## Setup

```bash
pip install -r requirements.txt
python -m pytest -q
```

Or open a notebook in Colab, which clones this repository and runs everything. `00_model_driver.ipynb` is the quick demonstration. `01_bridge_fire_ingest.ipynb` is the full ingest and takes considerably longer, since it reads satellite imagery and queries three external services.
