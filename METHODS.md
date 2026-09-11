# Methods

Full method, validation and results for **Scar Threshold**. The short version, with the live map, is in [README.md](README.md).

**Status:** complete pipeline, run end to end on two 2024 fires (Bridge and Line) through a single configuration-driven notebook. Model implementation cross-validated against the official USGS package. 184 tests passing.

---

## The problem

After a wildfire, two things happen to a hillside. The plants that held the soil in place are gone, and the soil itself often turns water repellent, because burned organic matter leaves a waxy layer near the surface. Rain that would normally soak in runs straight off instead.

When a short, intense burst of rain hits a steep burned slope, the loose material on that slope starts moving. It picks up more material as it goes, and what reaches the canyon bottom is a fast slurry of mud, rock and burned vegetation. That is a debris flow. They kill people and destroy infrastructure, usually in the first winter after a fire, and usually from storms that would be completely unremarkable on unburned ground.

The useful part is that they are predictable. Four things control whether a given canyon produces one: how steep it is, how badly it burned, how erodible the soil is, and how hard it rains. Staley and others (2017) fitted those four things to a database of real post-fire debris flows and produced a model that works well enough to run operational warning systems in the western United States.

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

**One notebook, any fire.** Everything fire-specific lives in a single configuration block at the top of `05_generalized_pipeline.ipynb`: the fire's name, its rough centre and published acreage from the incident page, the ignition date, and two date windows for the satellite search. The notebook builds its own sanity guards from those, suggests the best pre and post scenes, and runs through to the web export. Nothing below the configuration block changes between fires.

## Results: the 2024 Bridge Fire

The Bridge Fire burned about 56,000 acres of the San Gabriel Mountains northeast of Los Angeles, starting on 8 September 2024. It was chosen because it has extreme topography, dense high severity burn, real downstream exposure at Wrightwood and along the canyon corridors, and a published USGS assessment to compare against.

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

**How much does that depend on the assumptions?** Running the pipeline across three dNBR severity thresholds and two soil aggregation rules, the median basin's threshold sits between 16.2 and 17.9 mm/hr, a spread of 1.70 mm/hr. Only 17 of 237 basins change hazard class. Against the 7.7 mm/hr area-weighted disagreement with the USGS operational assessment (18.11 against 25.80 mm/hr, see validation below), parameter choice contributes roughly a fifth of what data-source choice does.

Substituting the BAER field-validated soil burn severity map, clipped to the fire perimeter, for the dNBR threshold puts 87 of 237 basins above the parameter envelope and none below it, so the envelope understates the real uncertainty. Every basin the parameter sweep rates never-High is confirmed not High by field observation, under both soil rules, with no exceptions. The disagreements run one way: this pipeline over-warns relative to ground truth and does not under-warn. Full analysis in `04_sensitivity.ipynb`, reproduced in `05_generalized_pipeline.ipynb`.

## Results: the 2024 Line Fire

The Line Fire started on 5 September 2024 north of Highland in the San Bernardino Mountains and reached a final size of 43,978 acres, through a mix of grass, chaparral and timber. It was chosen as the second fire for three reasons. Its severity profile differs from Bridge's (BAER rated 71% moderate or high, against 58% on Bridge). It has a published BAER soil burn severity map, so the anchor analysis can be repeated. And it sits in the same UTM zone and STATSGO region as Bridge, so any difference in the results comes from the fire rather than from new data handling.

An acreage of 39,234 also circulates for this fire. It predates a late-season flare-up and should not be used.

**Inputs**

| | Value |
|---|---|
| Perimeter | CAL FIRE FRAP, 179.6 km² (published final size 43,978 acres) |
| Pre-fire scene | Sentinel-2B, 20 August 2024, no cloud over the burn |
| Post-fire scene | Sentinel-2B, 19 October 2024, no cloud over the burn |
| Tiles | 11SMT and 11SNT |
| dNBR offset correction | -4.77, from 454,953 unburned pixels |
| Elevation | USGS 3DEP 10 m, 306 m to 3,314 m |
| Soil | USDA STATSGO, 9 map units (one with no KF: rock or water), basin S 0.239 to 0.263 |

**Choosing the post-fire scene.** The fire did not stop growing when it was mostly contained. Around 29 September it reached new dry fuel in the Bear Creek drainage and grew from about 39,300 to 43,890 acres over the next few days. Any post-fire scene from before that shows the Bear Creek ground unburned, while the final perimeter includes it, so the pipeline would score that area as unburned ground inside the fire. The notebook's automatic scene suggestion picked 24 September, because the post-fire search window had been set to start too early. The 19 October scene was used instead: the same satellite as the pre-fire scene, no cloud over the burn, and after growth had stopped. The general rule this produced is that the post-fire window should start after the fire's last growth, not after the start of containment, and the notebook's documentation now says so.

**What the terrain and imagery say**

- 85.0% of the burn area is moderate or high severity by dNBR (37.8% moderate, 47.2% high)
- 71.0% of the burn area is 23 degrees or steeper
- Mean slope across the whole extent is 19.0 degrees

Line is less steep than Bridge (71.0% against 83.0% of the burn at 23 degrees or more) but, by dNBR, more severely burned (85.0% against 76.5% moderate or high). Almost half the Line burn area is high severity by dNBR, against about a fifth by BAER, which is where most of the difference between the two severity sources sits on this fire.

**Basins**

171 drainage basins touching the fire, median size 0.53 km², all inside the model's calibration range. Together they cover 91.5% of the burn area, against 87.6% on Bridge. As there, the uncovered ground is trunk canyon floors too large to be source basins.

**Hazard**

Median basin needs **19.0 mm/hr** of 15 minute rainfall to reach a 50% chance of a debris flow, against 16.4 mm/hr on Bridge.

**Sensitivity.** Across the same six parameter combinations, the median basin's threshold sits between 18.7 and 20.4 mm/hr, a spread of 2.23 mm/hr. At 24 mm/hr, 92 basins are High under every combination, 20 flip, and 59 are never High.

**BAER anchor.** The BAER map covers 98.6% of the perimeter, so it includes the Bear Creek flare-up. Inside the perimeter it rates 50.2% moderate and 20.7% high, 70.9% combined, against 85.0% moderate-or-high from this project's dNBR. The published figures are 51% and 19%. The slightly higher share of high severity in the mosaic is consistent with the Phase 2 map released on 17 October 2024, which would cover the flare-up, but which version the national mosaic serves has not been confirmed.

Substituting the BAER map, clipped to the perimeter, puts 146 of 171 basin thresholds inside the parameter envelope, 24 above it and 1 below it. All 59 never-High basins are confirmed not High by BAER.

The single basin below the envelope (basin 183) is not a meaningful under-warning. It is an edge basin with only 18% of its area inside the perimeter and a T of about 0.02. BAER puts its threshold at 66.2 mm/hr against 66.7 mm/hr for the lowest parameter run, a difference of 0.4 mm/hr, which is about a fifth of the envelope's own median spread. Both numbers are nearly three times the 24 mm/hr design storm, and both rate the basin never High.

**Not yet done for Line:** the comparison against the published USGS assessment. It exists in the same ScienceBase 2024 collection as Bridge's.

## Results across both fires

| | Bridge | Line |
|---|---|---|
| Basins | 237 | 171 |
| dNBR vs BAER moderate-or-high | 76.5% vs 58% | 85.0% vs 70.9% |
| Burn area 23 degrees or steeper | 83.0% | 71.0% |
| Median basin size | 0.38 km² | 0.53 km² |
| Median basin threshold | 16.4 mm/hr | 19.0 mm/hr |
| Median parameter spread | 1.70 mm/hr | 2.23 mm/hr |
| Pipeline over-warns (BAER above envelope) | 87 basins (37%) | 24 basins (14%) |
| Pipeline under-warns (BAER below envelope) | 0 | 1, by 0.4 mm/hr at 66 mm/hr |
| Never-High basins confirmed not High by BAER | 80 of 80 | 59 of 59 |

Across two 2024 southern California fires, the pipeline over-warns relative to field-validated BAER severity (37% of basins on Bridge, 14% on Line) and does not meaningfully under-warn. No basin the pipeline rates never-High is rated High by BAER on either fire.

The direction held on both fires; the size did not. Line over-warns in about a third as many basins. That fits Line's mix of grass, chaparral and timber against Bridge's mostly chaparral, since chaparral is where satellite severity and soil severity diverge most, but two fires do not establish that explanation.

The percentages are shares of basins, not of burned area. Two fires from the same year in neighbouring mountain ranges show a pattern, not a rule.

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

The claims here are checked in four places, and the distinction between them matters.

### The model implementation, against the reference package

Given identical T, F, S and R values, `m1.py` produces bit for bit identical results to `pfdf.models.staley2017`, the official USGS implementation. That was checked across 1,422 forward evaluations (237 basins at 6 design storms) and 237 inverse solves. Maximum absolute difference: 0.000e+00. The same check runs inside the generalized notebook for every fire.

The comparison was then deliberately broken to confirm it is capable of failing. Swapping two coefficients moves the result by 1.3e-01, passing intensity where accumulation was expected moves it by 8.3e-01, and perturbing a single coefficient by 1% moves it by 4.0e-03. So the exact agreement is a real result, not a comparison that always returns zero. The captured values are frozen in `tests/test_m1_pfdf.py`, so the agreement holds as a regression test with no network access and no pfdf installed.

### The generalized pipeline, against the original runs

`05_generalized_pipeline.ipynb` replaces the Bridge-specific notebooks with one that reads everything from a configuration block. Its last cell compares a run against a previous validated one. Rerunning Bridge through it reproduces the original Bridge run on all 30 checks: the headline figures in this document, and every one of the 237 basins at full precision, with a largest difference of 4e-14 mm/hr in any threshold, which is floating point rounding. Rerunning Line reproduces an earlier Line run on all 19 checks across its 171 basins.

That matters for interpreting the second fire. The version that reads everything from configuration gives the same answer as the version with Bridge hardcoded throughout, so the differences between Bridge and Line come from the fires, not from the code.

### The model implementation, against USGS published output

USGS publishes T, F and S per catchment for their own Bridge Fire assessment (`brd2024`). Feeding their values into this project's model reproduces their published rainfall thresholds on all 703 pieces of burned ground to within floating point precision: mean difference 5.1e-15 mm/hr, maximum 4.7e-13 mm/hr, correlation 1.000000.

This is not a stronger version of the check above. Both reproduce the same published equation and both would have to agree. Its value is narrower and specific: it confirms that this project reads USGS's published fields and units correctly, and that this particular assessment was run with stock M1 parameters rather than the modifications USGS notes operational personnel sometimes make. Both are prerequisites for the input comparison below.

### The ingest, against an independent operational assessment

The two assessments were compared on a shared 10 m grid, because their 562 catchments (median 0.082 km²) and this project's 237 (median 0.379 km²) do not correspond one to one. Over the 218.7 km² both cover:

| Variable | correlation | median difference (ours minus theirs) |
|---|---|---|
| F, burn severity | 0.965 | +0.033 |
| T, terrain | 0.921 | +0.152 |
| S, soil | 0.917 | +0.110 |
| rainfall threshold | 0.877 | -5.08 mm/hr |

These are computed per pixel, but values are constant within each catchment, so the effective sample is in the hundreds rather than the millions of pixels compared. They describe spatial agreement; they are not statistical tests.

**The disagreement is one-directional.** Of ground USGS rates High at 24 mm/hr, this assessment agrees on 99.8%. Of ground this assessment rates High, USGS agrees on 63.9%. Only 0.2 km² out of 218.7 is High for them and not for us. The two agree on where the hazard is and differ on how much, with this project consistently more hazardous.

**F agreeing is the most informative result.** Their field description defines F as mean catchment dNBR divided by 1000, the same quantity used here, and the two agree at r = 0.965 despite different imagery and entirely separate processing. So the two pipelines agree on dNBR itself, which narrows the vegetation-versus-soil severity question to the moderate/high classification inside T rather than the dNBR measurement.

Running the model on the same ground with one variable swapped at a time attributes the 6.4 mm/hr median gap. (This is a median over the shared ground; the 7.7 mm/hr figure quoted elsewhere is the area-weighted gap between the two basin sets, a different summary of the same disagreement.) The swaps were run in both directions, because the model is non-linear and shares measured from one baseline need not match those measured from the other:

| Swapped variable | from USGS baseline | from our baseline | reported range |
|---|---|---|---|
| T, terrain | 46.3% | 48.0% | 46 to 48% |
| S, soil | 44.0% | 33.9% | 34 to 44% |
| F, burn severity | 5.7% | 15.9% | 6 to 16% |

Terrain is the firm number: under 2 percentage points of spread, so it accounts for roughly half the gap regardless of where the measurement starts. Soil and severity each move by about 10 points depending on the baseline and trade against each other, so they are reported as ranges rather than point estimates. The shares sum to 96.0% one way and 97.7% the other, so interaction between the variables is small in both directions.

Most of the soil difference sits in aggregation rather than in the data. Six candidate rules were computed from the same source: zeroing null KF values rather than dropping and renormalising them moves S from 0.259 to 0.197 against the USGS median of 0.150, closing 57% of the difference and coming closer than any other rule tested. That is suggestive rather than conclusive, since matching a median does not identify a rule and the USGS field description specifies only "mean catchment KF-factor".

Two alternative explanations were tested and eliminated. SSURGO moves S further away rather than closer, with coverage verified at 1.0000 across all 237 basins. And dividing by 100 rather than renormalising over the components present, which would matter where STATSGO component percentages fall short of 100, returns values identical to the zeroed rule here, because all ten map units in this fire sum to exactly 100.

### Substituting the USGS inputs directly

USGS documentation defines their terrain variable as the proportion of upslope area in BARC class 3 or 4 with gradients at or above 23 degrees. Those classes come from a field-validated soil burn severity map, not a fixed dNBR threshold: BAER teams set the class breaks per fire and hand-correct individual areas from field observation. For the Bridge Fire, BAER published the result as 51% moderate and 7% high, so 58% moderate-or-high, against the 76.5% this project's dNBR >= 270 classification produces.

That published raster was downloaded and verified against its own published class proportions (51.1% and 6.9% measured, within 0.2 points) before use, then substituted for this project's severity mask with everything else held fixed.

| Run | area-weighted T | area-weighted S | threshold | gap closed |
|---|---|---|---|---|
| this project's inputs | 0.670 | 0.254 | 18.11 mm/hr | - |
| BAER severity substituted | 0.471 | 0.254 | 19.95 mm/hr | 24% |
| zeroed soil rule | 0.670 | 0.183 | 19.57 mm/hr | 19% |
| both substituted | 0.471 | 0.183 | 21.69 mm/hr | 47% |
| USGS published | 0.376 | 0.144 | 25.80 mm/hr | - |

Delineation scale was also tested and contributes nothing. The pipeline was run at four minimum basin areas from 0.02 to 0.5 km². The 0.02 km² run matches the threshold USGS documents for their own drainage networks and produced 566 basins at a median of 0.070 km², against their 562 at 0.082 km². Across that 25-fold range of minimum area, the area-weighted T moves by 0.05 and the threshold by 0.35 mm/hr, in the opposite direction to the one that would close the gap.

The full analysis is in `03_sensitivity_delineation.ipynb`.

### What is still not validated

**A residual of 4.11 mm/hr, about half the original gap, is unexplained and sits in the terrain variable.** Using the USGS field-validated severity map at the USGS delineation scale, T is 0.471 against their 0.376, still 25% higher. Delineation scale has been ruled out and severity classification accounts for part of it, so something else in the terrain step differs. The leading untested hypothesis is that "upslope area" in the USGS definition refers to the drainage network above a stream segment rather than to a catchment polygon, which need not be the same region even when the areas are comparable.

**The soil substitution is fitted, not verified.** The zeroed null rule was chosen because it came closest to the USGS values among six candidates tested, so reporting it as an explanation carries that circularity. The severity substitution does not: the BAER raster is the actual published input and was checked against its own published class proportions before use.

**A residual soil difference of 0.047 is unexplained.** Zeroing null KF values accounts for 57% of the soil gap and two further mechanisms have been tested and eliminated. Resolving the remainder would require knowledge of the `ocelote` implementation that the published outputs do not provide.

**The USGS catchments sit below the calibration floor cited here.** Their median catchment is 0.082 km², while this project treats 0.1 km² as the lower bound of the range M1 was fitted on and flags anything below it as an extrapolation. By that rule more than half of the USGS operational catchments would be flagged. Either the range is cited too strictly here or operational practice routinely works below it, and that is unresolved.

**The reference ingest code has not been run.** `pfdf.severity`, `pfdf.watershed` and `pfdf.segments` were not used. The comparison is against published assessment output, not against the reference implementation of the ingest.

**Their assessment is not a stock reference either.** USGS notes that operational personnel may modify stream network delineation and model parameters for individual assessments. Their perimeter is also 221.3 km² against the 226.6 km² used here, and their assessment date is one day before this project's post-fire scene, so the two necessarily used different imagery.

**The USGS comparison covers Bridge only.** Line has a published USGS assessment that has not yet been compared.

The full comparison is in `02b_usgs_comparison.ipynb`.

## How it actually works, step by step

**Burn severity from two satellite pictures.** Healthy vegetation reflects near infrared light strongly and shortwave infrared weakly. Burned ground does the opposite. The Normalised Burn Ratio combines those two bands into a single number, and subtracting the after picture from the before picture gives dNBR, which is a map of how much changed.

Two pictures taken 40 days apart also differ for boring reasons: sun angle, atmosphere, slight seasonal change. So the pipeline looks at unburned land in a ring around the fire, where the answer should be zero, and measures what it actually says. Whatever that is, is the bias, and it gets subtracted from everything. On the Bridge Fire it came out at -5.05, which is tiny, mostly because both scenes came from the same satellite in the same dry season.

**Choosing the scenes.** For every candidate date in the search windows, the notebook measures how much of the perimeter the tiles cover and how much cloud and snow the Sentinel-2 scene classification shows inside the perimeter, rather than the whole-scene cloud figure, which can be high while the fire itself is clear. It then suggests the earliest clean post-fire date paired with the latest clean pre-fire date from the same satellite. A date set in the configuration always overrides the suggestion. The scene classification often misses smoke, so the dNBR map is still checked by eye, and the suggestion cannot know when a fire stopped growing (see the Line Fire results).

**Slope from an elevation model.** Slope is computed with Horn's method, the same 3x3 kernel that GDAL and ArcGIS use, so the numbers are comparable to standard GIS output.

**Flow routing needs the DEM repaired first.** Water flows to the lowest neighbouring cell. That breaks down when a cell has no lower neighbour, which happens constantly in real elevation data: small pits from measurement noise, and genuine closed depressions. Water routed into a pit has nowhere to go, and the flow network dies there, splitting one real canyon into several fake ones.

So three steps run before routing. Fill the pits. Resolve the flats that filling creates, since a perfectly flat cell has no lowest neighbour either. Then assign every cell a direction to its steepest neighbour and count how many cells drain through each point.

On the Bridge Fire, 0.79% of cells were altered by filling. The deepest fill was 74.7 m, which turned out to be San Gabriel Reservoir. A reservoir is a real closed depression and filling it is correct.

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
    sensitivity.py envelopes, stability classes, anchor agreement
    _compat.py     numpy 2 shim for pysheds
tests/             184 tests across 9 files
00_model_driver.ipynb             Colab driver: pulls this repo, runs it, shows results
01_bridge_fire_ingest.ipynb       original Bridge Fire ingest
02b_usgs_comparison.ipynb         comparison against the published USGS assessment
03_sensitivity_delineation.ipynb  delineation scale and USGS input substitution
04_sensitivity.ipynb              original Bridge parameter sensitivity and BAER anchors
05_generalized_pipeline.ipynb     any fire, perimeter to web export, from one config block
web/                              the live map: index.html, app.js, style.css, data/
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

**BAER anchor severity is clipped to the fire perimeter.** The BAER national mosaic shows every assessed fire in a region, without labelling which pixel belongs to which fire, and basins extend outside the perimeter to capture their full upstream area. Without the clip, an edge basin can pick up severity from a neighbouring, older fire. On Line, an older burn scar to the southeast sat inside several edge basins and produced 4 of 5 apparent under-warnings; one basin had 46% of its area in that scar. With the clip, those four disappear and the over-warning count does not change. On Bridge, which has no neighbouring scar in the mosaic, the clip removed 0.05 km² of BAER severity from inside basins and moved 18 thresholds by at most 0.2 mm/hr, with no basin changing its agreement class. dNBR is not clipped: it measures change between the two scene dates, so an old neighbouring scar reads as roughly zero change anyway.

**The perimeter search guards are built, not typed.** The configuration takes the fire's rough centre and published acreage from the incident page. The notebook builds a search box 0.3 degrees around the centre and accepts a perimeter between half and double the published area. These only decide whether a perimeter query result is trusted, and never change the results.

## Testing

```bash
python -m pytest -q          # 184 passed
```

A wrong hazard map looks exactly like a correct one, so correctness here cannot be established by looking at it. The tests are built around that.

Slope is checked against planes whose angle is known from trigonometry. The three classic errors above each have a test that fails if reintroduced. `test_compat.py` runs real D8 flow accumulation on a generated GeoTIFF, so if pysheds ever ships a numpy 2 compatible release, deleting the shim is either immediately safe or immediately not.

Basin delineation is tested on synthetic flow grids small enough to verify by hand: a 3x3 where all eight neighbours drain to the centre catches a mis-encoded direction map, which would otherwise produce basins that drain the wrong way and look perfectly normal. There is also a property test on random grids checking that every labelled cell reaches its own basin's outlet before any other, a determinism test because greedy algorithms with tied sort keys silently reorder, and a cross-check against `pysheds.Grid.catchment` on a real DEM.

`sensitivity.py` is tested on hand-built frames small enough to verify by eye. Two tests pin the High cutoff specifically: one confirms a basin at p = 0.55 comes out never-High rather than High, and one confirms p = 0.60 exactly counts as High. Another asserts F is constant per basin across runs, because F not varying with the severity threshold is a load-bearing property of that study's design, and a frame where it varies was assembled wrongly. `anchor_agreement` refuses to run if an anchor run appears in the envelope list, so the structural mistake that would quietly widen the envelope is prevented by the code rather than by remembering.

The model tests are described under validation above. The generalized notebook adds a regression check against a previous validated run as its final cell, described there too.

## Known limitations

**Vegetation change is not soil burn severity.** The 270 dNBR threshold used here classifies moderate and high severity from vegetation change. M1 was calibrated against soil burn severity, which USGS maps with BAER field teams. The two correlate but are not the same, and in chaparral they diverge in a known direction: the shrubs burn completely, giving very high dNBR, while the soil underneath may only be moderately affected. Thresholds of 200, 270 and 350 are run as a sensitivity axis, and BAER is substituted directly as an anchor.

This has been measured rather than predicted. On Bridge, BAER published the field-validated soil burn severity as 51% moderate and 7% high, so 58% moderate-or-high, against the 76.5% produced here. On Line the figures are 70.9% against 85.0%. Substituting the Bridge raster drops the terrain variable from 0.670 to 0.471 and closes 24% of the difference with the USGS assessment. The overstatement is slope-independent, and it is largest in moderately burned basins: where the fire burned hardest, satellite dNBR and field soil severity agree, and where it burned patchily they diverge.

The comparison also narrows what is at issue. On Bridge, their F, which is mean catchment dNBR, agrees with this project's at r = 0.965, so the two pipelines measure dNBR consistently. The gap is in the classification applied to it, not in the measurement.

**Basins cover 87.6% (Bridge) and 91.5% (Line) of the burn area, not all of it.** Trunk canyons with more than 8 km² of contributing area are outside the model's calibration range and cannot serve as source basins. Those unassigned valley floors are exactly where debris flows travel and where damage occurs, so the map describes where flows initiate rather than where they end up.

**S barely varies.** STATSGO map units are 1 to 10 km² against a median basin of 0.38 km², so most basins sit inside a single map unit. Across the entire Bridge Fire, S spans 0.242 to 0.339, and across Line only 0.239 to 0.263. Its coefficient is the largest in the model, but with that little spread it acts closer to a constant offset than a discriminator. Almost all the between-basin variation in the results comes from T.

**The ingest is compared but not fully explained.** See the validation section. It agrees with the USGS assessment on spatial pattern and on dNBR, and differs systematically on terrain and soil. The terrain difference is not separated from the basin size difference, and the soil aggregation rule is inferred from a distribution match rather than identified.

**Likelihood only.** The Gartner (2014) volume model and the combined hazard classification are not implemented, so this says how likely a debris flow is, not how big.

**Two fires, one scene pair each.** Both are 2024 fires in neighbouring southern California ranges. Scene choice is not yet a sensitivity axis. The over-warning found against BAER held in direction on both fires but was about a third as frequent on Line, which is consistent with, but does not show, a dependence on fuel type. A fire in different fuels, such as the 2024 Park Fire in northern California mixed conifer and oak, is what would test that.

**The two-fire percentages are shares of basins.** Basins differ in size, so "37% of basins" is not "37% of burned area".

**Basin coverage of the burn depends on delineation scale.** The Bridge 87.6% figure is for the 0.1 km² minimum. At 0.02 km² it rises to 93.7%, because fewer trunk channels exceed the 8 km² ceiling. The uncovered ground is a consequence of the scale chosen rather than a fixed property of the method.

## Roadmap

1. ~~Verify Soil Data Access connectivity and schema~~ **done**, live STATSGO output captured as a fixture
2. ~~Real data ingest: Sentinel-2 and 3DEP for the 2024 Bridge Fire~~ **done**
3. ~~Cross-validate the model against the official USGS `pfdf` package~~ **done**, exact agreement, pinned as a test
4. ~~Compare against the published USGS Bridge Fire assessment~~ **done**, see `02b_usgs_comparison.ipynb`
5. ~~Delineation scale sensitivity and substitution of the published USGS inputs~~ **done**, see `03_sensitivity_delineation.ipynb`
6. ~~Sensitivity analysis: which basins are High under every assumption, and which flip~~ **done**, see `04_sensitivity.ipynb`. 140 basins are High under all six parameter combinations, 17 flip, 80 never are. Median threshold spread 1.70 mm/hr
7. ~~Delivery~~ **done**, live map on Cloudflare Pages, reading a manifest plus one GeoJSON per fire
8. ~~A second fire, through a single configuration-driven notebook~~ **done**, Line Fire 2024, see `05_generalized_pipeline.ipynb`
9. Compare Line against its published USGS assessment
10. A fire in different fuels (Park Fire 2024) to test whether the over-warning depends on fuel type
11. Test the leading hypothesis for the 4.11 mm/hr terrain residual: USGS summarising over stream segments rather than catchment polygons
12. On-demand runs: a user supplies a perimeter and dates, a job runs the pipeline and adds the result to the map

## References and attribution

- Staley, D.M., Negri, J.A., Kean, J.W., Laber, J.L., Tillery, A.C., Youberg, A.M. (2017). Prediction of spatially explicit rainfall intensity-duration thresholds for post-fire debris-flow generation in the western United States. *Geomorphology*, 278, 149-162.
- Gartner, J.E., Cannon, S.H., Santi, P.M. (2014). Empirical models for predicting volumes of sediment deposited by debris flows and sediment-laden floods in the transverse ranges of southern California. *Engineering Geology*, 176, 45-56.
- King, J.M. USGS `pfdf` package, the authoritative implementation of these models. This project's `m1.py` is a transparent, independently tested reimplementation intended for cross-checking, not as a replacement. https://code.usgs.gov/ghsc/lhp/pfdf
- Sentinel-2 L2A via the Microsoft Planetary Computer STAC catalogue
- USGS 3DEP 1/3 arc-second elevation
- USDA NRCS Soil Data Access, STATSGO2
- CAL FIRE FRAP historic fire perimeters
- USDA Forest Service BAER Soil Burn Severity Classification, national mosaic, used as the field-validated severity anchor for both fires
- Line Fire final acreage, containment history and the Bear Creek flare-up: CAL FIRE incident page, InciWeb daily updates, and San Bernardino County incident information

## Setup

```bash
pip install -r requirements.txt
python -m pytest -q
```

Or open a notebook in Colab, which clones this repository and runs everything. `00_model_driver.ipynb` is the quick demonstration. `05_generalized_pipeline.ipynb` runs any fire from perimeter to web export and takes considerably longer, since it reads satellite imagery and queries four external services.
