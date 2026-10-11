# Assumptions, data sources, limitations (say these out loud to judges)
**Data:** India-WRIS manual groundwater levels (depth below ground), Pune region, 145 wells with >=6 pre-monsoon years, 2009-2023. All six blueprint factors are loaded: rainfall (CHIRPS Jun-Sep 2014-2023), soil infiltration (SoilGrids sand/clay 0-30 cm), slope (Copernicus DEM, used in intervention rules), structures (OpenStreetMap within 2.5 km; incomplete in rural India), demand = PROXY (ESA WorldCover cropland + built-up share, not CGWB extraction data). 26 invalid soil values were replaced by the nearest valid cell.
**Score:** 0-100 relative priority. Wells part = 0.6 x stress (45% depth, 55% decline) + 0.4 x seasonal recovery, spatially predicted (XGBoost + IDW), validated on unseen wells (R² ≈ 0.26). Weights follow the blueprint (30/20/15/15/10/10); missing factors are dropped and weights renormalised.
**Tiers:** High = top 20% of zones, Medium = next 30%, Low = rest (relative, not absolute).
**Interventions:** hand-written suitability rules, not hydrological simulation.
**Costs/benefits:** illustrative placeholders (₹ lakh / units), not verified local estimates.
**What-if:** rainfall scales recharge potential and benefit; extraction scales stress (elasticity 0.5). Scenario estimates, not forecasts.
**Optimizer:** greedy by benefit per rupee with spacing and diversity limits; not provably optimal.
**Do not claim:** guaranteed recharge, groundwater prediction, field-level certainty, or a tested Bedrock/Strands deployment.
Suggested line: "Our prototype creates a transparent, data-driven shortlist of where limited recharge investment should be investigated first."
