# Pie360 Recession Model Audit

**Audit date:** 2026-05-27  
**Scope:** `models/recession_model.py`, `models/cycle_classifier.py`, `models/backtest.py`, `models/phase_returns.py`, `models/historical_parallels.py`, `components/cycle_engine.py`

---

## 1. Current Model Summary

### Architecture

The recession probability engine is a **6-feature weighted linear stress aggregator**, not a statistical logit in any classical sense. The name "weighted logit" in the module docstring is a misnomer: there is no sigmoid applied to the final output, and no coefficients were estimated from data. The architecture is:

1. Each raw FRED value is mapped to a stress score in [0, 1] via a hand-tuned logistic function (`_logistic(x, k)`).
2. Stress scores are multiplied by feature weights and summed.
3. The raw weighted sum (also in [0, 1]) is multiplied by 100 to produce a "probability" in [0, 100].
4. Traffic lights are applied: green < 25, yellow 25–49, red ≥ 50.

The output is therefore a **linear combination of per-feature logistic transforms**, not a calibrated probability in the frequentist or Bayesian sense. Calling it a probability is a UX choice, not a statistical claim.

### Feature List and Weights

| # | Feature | FRED Series | Weight | Stress Function Centre | k (steepness) |
|---|---------|-------------|--------|------------------------|---------------|
| 1 | 10Y–3M Treasury Spread | T10Y3M | **0.30** | 0% (flat) | `k=1/0.5=2.0` |
| 2 | Sahm Rule | SAHMREALTIME | **0.20** | +0.25 (midpoint) | `k=1/0.12≈8.3` |
| 3 | CFNAI 3-month avg | CFNAI | **0.20** | −0.10 (near 0) | `k=1/0.3≈3.3` |
| 4 | Chicago Fed NFCI | NFCI | **0.10** | 0 (neutral) | `k=1/0.25=4.0` |
| 5 | Initial Claims YoY % | ICSA | **0.10** | +5% YoY | `k=1/8.0=0.125` |
| 6 | HY OAS | BAMLH0A0HYM2 | **0.10** | 450 bps | `k=1/80≈0.0125` |

Weights sum to exactly 1.0. ISM Manufacturing PMI (NAPM) was removed from FRED ~2024 due to ISM licensing; its former 5% weight was redistributed to CFNAI, which grew from 0.15 to 0.20.

### Output Calculation (verbatim)

```
weighted_stress = sum(weight_i * stress_i)   # result in [0, 1]
probability = weighted_stress * 100           # result in [0, 100]
```

### Backtest Coverage

The backtest engine (`models/backtest.py`) runs the model point-in-time at monthly frequency from 1997-01 to present, constrained by the HY OAS series which starts 1996-12-31. This covers three NBER recessions:
- 2001 dot-com (Mar–Nov 2001)
- 2007–09 Great Recession (Dec 2007–Jun 2009)
- 2020 COVID (Feb–Apr 2020)

The backtest includes a `compute_recession_stats()` function that computes first-crossing lead times for the 25% and 50% thresholds, and `compute_false_positive_periods()` that identifies elevated signals not followed by recession within 12 months. However, **no calibration statistics are stored in the codebase** — no AUROC, no Brier score, no false-positive rate is computed or logged anywhere. The Backtest page (page 1) presumably displays charts derived from this engine, but no quantitative summary of model performance is hardcoded or auto-computed anywhere that would surface in the audit. This is the single biggest gap in model governance.

---

## 2. Feature Weight Critique

### Feature 1: 10Y–3M Treasury Spread (T10Y3M) — Weight 0.30

**Current weight: 0.30 — too high for 2020+ regime, directionally correct otherwise.**

The 10Y–3M spread is the best single predictor in the Estrella & Mishkin (1996, JME) literature, and a foundational feature in the NY Fed recession probability model. The NY Fed model uses the spread as its *only* input and still achieves strong AUROC (~0.85 over 1960–2010). A 0.30 weight is defensible for pre-2020 history.

However, the stress function `_logistic(-value / 0.5)` produces high stress (>0.73) any time the spread is below 0, regardless of economic context. The 2022–2024 inversion was the deepest and longest since 1981, yet the 2023–2024 economy did not enter recession. The function has no mechanism to distinguish a Fed-driven inversion driven by a rates shock from a demand-driven inversion. A reasonable structural fix is to condition on the *level* of the short rate (when the 3M yield is above 5%, inversion is more likely demand-destruction signal than financial stress). The logistic centre should also be shifted slightly negative (−0.25%) to reduce false positives in shallow inversions.

**Suggested weight: 0.25. Suggested stress function adjustment: shift centre to −0.25% from 0%.**

Academic reference: Estrella & Trubin (2006 FRBNY Economic Policy Review) show the 10Y–3M is superior to 10Y–2Y at the 4-quarter horizon.

---

### Feature 2: Sahm Rule (SAHMREALTIME) — Weight 0.20

**Current weight: 0.20 — justified but the stress function is poorly calibrated.**

The Sahm Rule is a near-perfect coincident indicator by design: Claudia Sahm (2019, Brookings) calibrated the 0.50 threshold against every NBER recession since 1970 with zero false positives in the in-sample period, and one borderline case (early 2022 COVID reopening surge caused a transient Sahm reading near 0.4 before reversing). A weight of 0.20 is appropriate for a highly reliable coincident signal.

The problem is the stress function: `_logistic((value - 0.25) / 0.12)`. The logistic steepness `k = 1/0.12 ≈ 8.3` means stress rises very sharply around 0.25, which is not an empirically meaningful threshold. At 0.25, the stress score is 0.50 — meaning the Sahm feature alone contributes 10 pp to the recession probability (0.20 × 0.50 × 100) when there has been zero historical recession at that level. The meaningful threshold is 0.50. The centre should be shifted to 0.40 and steepness reduced.

**Suggested weight: 0.20 (keep). Suggested stress function: centre at 0.40 (not 0.25), steepness k ≈ 5.0.**

Note: The Sahm Rule is inherently *coincident*, not leading. In a real-time system, it confirms rather than predicts. Its 0.20 weight is fine if the goal is signal robustness (prevent missing a recession in progress), but it contributes little to early warning.

---

### Feature 3: CFNAI 3-month Average (CFNAI) — Weight 0.20

**Current weight: 0.20 — inflated by the NAPM redistribution; partially justified.**

The CFNAI is a factor-model composite of 85 monthly indicators. The Chicago Fed documentation states that the CFNAI-MA3 below −0.70 is associated with recession "with some regularity." This is calibrated empirically. The stress function `_logistic((-value - 0.1) / 0.3)` produces 50% stress at CFNAI = −0.10, which is well above-trend slowdown territory, not recession. The function is too sensitive to minor below-trend readings.

The 0.15→0.20 weight increase to absorb ISM PMI was pragmatic but untested. CFNAI already *includes* ISM manufacturing in its factor construction (it draws on industrial production subcomponents), so adding back 5% of ISM weight via CFNAI is not a clean substitution — it amplifies manufacturing cycle signals at the expense of other dimensions.

**Suggested weight: 0.15 (revert). Suggested stress function: shift centre to −0.35 (closer to the −0.70 threshold).**

Academic reference: Evans, Liu, Pham-Kanter (2002) CFNAI paper documents the −0.70 threshold calibration.

---

### Feature 4: Chicago Fed NFCI (NFCI) — Weight 0.10

**Current weight: 0.10 — defensible but the stress function is too aggressive.**

The NFCI is constructed to have mean 0 and standard deviation 1 by design. An NFCI above +0.5 is a genuine tightening signal historically correlated with credit events and recession risk. The stress function `_logistic(value / 0.25)` produces 88% stress at NFCI = +0.75, which is aggressive but not unreasonable given that NFCI readings above +1.0 have occurred in 2008–09, 2020, and COVID. The description thresholds in the code (>0.50 = "significantly tightened") are reasonable.

However, the function produces 50% stress at NFCI = 0 (perfectly neutral conditions), which means in normal/loose financial conditions the model is never below 5 pp of base recession risk from this feature alone. This creates a permanent floor that suppresses the true "all-clear" signal. The centre should be shifted to +0.25.

**Suggested weight: 0.10 (keep). Suggested stress function: centre at +0.25.**

Academic reference: Brave & Butters (2011, Chicago Fed Economic Perspectives) on NFCI construction and recession predictability.

---

### Feature 5: Initial Claims YoY % (ICSA) — Weight 0.10

**Current weight: 0.10 — correct weight; stress function threshold calibration is weak.**

Initial claims are a weekly leading indicator with a typical lead of 2–6 months before NBER recession onset. The YoY transformation is sensible for removing seasonal noise. The stress function centres stress at +5% YoY with steepness k = 1/8 = 0.125, which is notably flat — the logistic barely moves from 0.35 to 0.65 across the range of +0% to +20% YoY. This means claims almost never drive a strong stress signal even when genuinely elevated.

The empirical threshold in recessions is closer to +20–30% YoY sustained for 4+ weeks, not 15% as implied by the description string. The mid-point should be moved to +15% YoY and steepness increased (k ≈ 0.20).

Additionally, the YoY calculation in `compute_icsa_yoy()` uses `iloc[-56:-52]` for the year-ago window, which compares current 4-week average to weeks 52–56 ago. This is correct for weekly data but creates noise if the year-ago window happens to catch a holiday distortion (e.g., Thanksgiving claims). A 4-week average of the year-ago period (weeks 52–55) is already implemented and handles this adequately.

**Suggested weight: 0.10 (keep). Suggested stress function: centre at +15% YoY, k = 0.20.**

---

### Feature 6: HY OAS (BAMLH0A0HYM2) — Weight 0.10

**Current weight: 0.10 — defensible; threshold calibration is the best in the model.**

HY OAS is a financial conditions indicator with strong recession-predictive content. The 700 bps threshold noted in the description strings aligns with: GFC peak (~1900 bps), 2015–16 energy-sector stress (~850 bps), 2020 COVID peak (~1100 bps). The stress centre at 450 bps with k = 1/80 is appropriately calibrated — 450 bps is roughly the long-run average excluding recessions. This is the most empirically grounded stress function in the model.

One concern: HY OAS reacts quickly to equity volatility and can spike and reverse within weeks during non-recessionary risk-off events (e.g., August 2015, December 2018). A 4-week moving average of OAS would reduce noise. The raw latest value is currently used.

**Suggested weight: 0.10 (keep). Minor improvement: apply a 4-week moving average before computing stress.**

---

### Revised Weight Table

| Feature | Current Weight | Suggested Weight | Key Change |
|---------|---------------|-----------------|------------|
| T10Y3M | 0.30 | 0.25 | Reduce; too many 2022–24 false positives |
| SAHMREALTIME | 0.20 | 0.20 | Keep weight; fix stress centre to 0.40 |
| CFNAI | 0.20 | 0.15 | Revert ISM redistribution; shift stress centre |
| NFCI | 0.10 | 0.10 | Keep; shift stress centre to +0.25 |
| ICSA | 0.10 | 0.10 | Keep; steepen function, shift centre to +15% |
| BAMLH0A0HYM2 | 0.10 | 0.10 | Keep; add 4-week MA pre-processing |
| **New: Leading Index** | — | **0.10** | Add USSLIND (Conference Board LEI) |

Revised weights sum to 1.00. The freed 0.05 from T10Y3M and 0.05 from CFNAI are reallocated to a new LEI feature (see Section 3).

---

## 3. Additional FRED Series Worth Adding

### 3.1 Conference Board Leading Economic Index — USSLIND

**FRED series:** `USSLIND`  
**Typical lead:** 6–9 months before recession onset (range 1–15 months in NBER comparisons)  
**Coverage:** 1959–present (monthly)

The Conference Board's LEI is already partially acknowledged in the codebase — `compute_lei_growth()` in `fred_client.py` is implemented and exported, and `cycle_classifier.py` accepts `lei_growth` as an input — but USSLIND is **not included in the recession model feature list** and carries zero weight in `_FEATURES`. This is the single most impactful gap. The LEI incorporates 10 subcomponents (including 2 already in the model — claims and yield spread) and its 6-month diffusion signal reliably turns negative 2–3 months before every recession since 1970.

**Integration:** Compute 6-month annualised growth (already done in `compute_lei_growth()`). Stress function: `_logistic((-growth - 1.0) / 2.0)` — 50% stress at −1% annualised growth, high stress at −5% (consistent with recession episodes). Suggested weight: 0.10.

---

### 3.2 ISM Non-Manufacturing Business Activity — via FRED surrogate

**FRED series:** `NMFBAI` (ISM Non-Manufacturing Business Activity Index) or `RSXFS` (retail sales ex-food)  
**Typical lead:** 1–3 months (coincident to slightly leading)  
**Coverage:** NMFBAI from 1997; RSXFS from 1992 (monthly)

The code notes attempt to use `NMFCI` for ISM services, which was never a valid FRED series. ISM Services (non-manufacturing) is a critical gap given services now constitute ~77% of US GDP. `RSXFS` (retail sales ex-food services) is an acceptable FRED proxy: it captures consumer cyclical spending and tends to turn negative 1–2 months before NBER recession onset. Stress function: `_logistic((-yoy_pct - 1.0) / 2.0)` where `yoy_pct` is the 3-month average YoY change.

Alternatively, the NFCI's Nonfinancial Leverage subcomponent (`NFCINONFINLEVERAGE`) provides a services-sector financial stress proxy that FRED does carry.

**Integration:** Fetch `RSXFS`, compute 3-month average YoY % change. Suggested weight: 0.05.

---

### 3.3 Consumer Confidence Leading Component — UMCSENT or OECD CLI

**FRED series:** `UMCSENT` (University of Michigan Consumer Sentiment, already in SERIES_META) or `OECD_CLI` via OECD API  
**Typical lead:** 3–6 months (turning points coincide with or slightly lead NBER)  
**Coverage:** UMCSENT from 1978 (monthly)

`UMCSENT` is already fetched for Tab 7 but not used in the model. Its 12-month rate of change (not level) is a useful recession signal — a YoY decline of >10% in Michigan Sentiment has preceded every recession since 1980 with a median lead of 4 months. The raw level is less useful due to secular trends.

**Integration:** Compute 12-month % change in UMCSENT. Stress function: `_logistic((-yoy_pct - 5.0) / 5.0)` — 50% stress at −5% YoY, high stress at −15% YoY. Suggested weight: 0.05.

---

### 3.4 Credit Impulse / C&I Loan Growth — BUSLOANS

**FRED series:** `BUSLOANS` (Commercial and Industrial Loans, all commercial banks)  
**Typical lead:** 4–8 months (credit contraction typically precedes recession)  
**Coverage:** 1947–present (weekly/monthly)

C&I loan growth turning negative has been a strong pre-recession signal. The 2-quarter YoY change in C&I loans turned negative before the 2001, 2008, and 2020 recessions. It is orthogonal to the yield curve and HY OAS — it captures actual lending behavior rather than market pricing, and it picks up credit tightening that doesn't yet show in spreads (e.g., bank pullback after a regional banking stress event). Not currently in the model at all.

**Integration:** Compute 6-month annualised growth rate of the 4-week moving average. Stress function: `_logistic((-growth - 1.0) / 3.0)`. Suggested weight: 0.05.

---

### 3.5 Building Permits YoY — PERMIT

**FRED series:** `PERMIT` (already in SERIES_META, fetched for Tab 7)  
**Typical lead:** 9–15 months (longest leading indicator in the standard set)  
**Coverage:** 1960–present (monthly)

Building permits are the longest-leading component of the Conference Board LEI and are already fetched but not included in the recession model. A sustained YoY decline of >15% in total permits has preceded every recession in the dataset (with one semi-false positive in 2022 when permits fell sharply on rate shock but the economy did not contract). The long lead time makes it most useful for early warning rather than confirmation.

**Integration:** Compute 6-month average YoY % change. Stress function: `_logistic((-yoy_pct - 10.0) / 8.0)`. Suggested weight: 0.05.

---

## 4. XGBoost vs Weighted Logit

### The Case For

XGBoost trained on NBER recession binary labels (USREC) with the current 6 features as predictors would offer several advantages:

1. **Non-linear interactions.** The current model assumes features contribute independently and linearly in stress-space. In reality, combinations matter — a simultaneous inversion + claims spike is qualitatively more dangerous than either alone. XGBoost handles this via tree splits at no additional engineering cost.
2. **Data-driven weights.** Current weights are arbitrary (by the author's own admission — there is no reference to an empirical weight-estimation step). XGBoost feature importance scores would reveal whether T10Y3M genuinely deserves 3x the weight of HY OAS.
3. **Calibrated output.** After fitting, Platt scaling or isotonic regression can turn XGBoost's raw score into a calibrated probability that matches empirical recession frequency, unlike the current system where "55% probability" is not interpretable against historical base rates.

### The Case Against

1. **Sample size.** FRED data from 1997 (model's start) covers 3 recessions — roughly 40 NBER recession months out of ~330 total. From 1960 (full FRED history), this expands to 9 recessions and ~120 recession months out of ~780 total. Training an XGBoost model with, say, 20 features on 780 observations with heavy class imbalance (recession: ~15%) is feasible in principle, but standard XGBoost has hundreds of parameters and will overfit to the idiosyncrasies of 9 historical events.

2. **Feature revision history.** Some FRED series have been revised substantially. Point-in-time CFNAI, SAHMREALTIME, and ICSA data is available from FRED vintages, but constructing a clean real-time dataset for all 6 features back to 1960 is non-trivial. Training on revised data introduces look-ahead bias that inflates apparent performance.

3. **Regime non-stationarity.** Each recession has a different driver (demand collapse, financial crisis, external shock, pandemic). A tree model trained on the 2008 pattern may not generalize to a 2030 pattern driven by, say, fiscal contraction. The current hand-tuned model is at least transparent about its causal theory.

4. **Interpretability.** The current model's feature contributions (the `FeatureContribution` dataclass and the per-feature stress display) are a key product feature — users can see exactly why the model is elevated. SHAP values can replicate this for XGBoost, but it adds implementation complexity.

5. **Maintenance.** XGBoost requires periodic retraining as the macroeconomic dataset grows, and a retraining protocol needs to be defined. The current rule-based system requires no retraining — only threshold recalibration.

### Recommendation

**Do not replace with XGBoost at this stage. Do adopt a hybrid approach.**

The immediate highest-ROI improvement is not model architecture but **stress function recalibration**: fit the logistic parameters for each feature using maximum likelihood against NBER recession months. For each feature, find the centre `mu` and steepness `k` that maximize the log-likelihood of recession = 1 when stress is high. This can be done with 50 lines of scipy code on the FRED backtest dataset and would transform the current arbitrary thresholds into empirically derived ones, without changing the model's interpretability or maintenance profile.

A secondary improvement is to compute and display a Brier score and AUROC on the backtest output — these are easy to add to `compute_recession_stats()` and would immediately surface whether the model is better or worse than random.

If you reach 5+ recessions in the backtest (add pre-1997 history for features that support it), or if you add 5+ features (Section 3), then a **logistic regression** (not XGBoost) with L2 regularization is the appropriate next step — it is statistically principled, retains interpretability, generalizes better than trees on small datasets, and its coefficients are directly analogous to the current weights.

---

## 5. Cycle Phase Classifier Critique

### Two Separate Classifiers

There are **two distinct cycle phase systems** in the codebase that are not reconciled:

**System A:** `models/cycle_classifier.py` — `classify_cycle_phase()` — uses recession probability + LEI growth + UNRATE trend. Produces 6 states: Early Expansion, Mid Expansion, Late Expansion, Peak, Contraction, Trough.

**System B:** `components/cycle_engine.py` — `detect_cycle_phase()` — uses 5 FRED series (T10Y2Y, UNRATE, INDPRO, CPIAUCSL, ICSA) scored independently with a weighted vote. Produces 4 states: Early/Recovery, Mid/Expansion, Late/Peak, Contraction.

These two systems can disagree in real time. If the main dashboard displays one and a sub-page displays the other, users see inconsistent cycle labels. Which is authoritative is not documented.

### System A (models/cycle_classifier.py) — Logic Assessment

**Strengths:**
- The `≥2 confirming indicators` requirement before committing to a phase is sound — it prevents whipsaw on single noisy prints.
- The data quality cap (`_apply_data_quality_cap()`) — reducing confidence when high-weight features are stale — is a well-designed defensive mechanism.
- NBER override (`nber_active=True`) correctly bypasses probabilistic logic when the authoritative source has spoken.

**Weaknesses and misclassification risks:**

1. **No "Trough" state is reachable.** The docstring declares six states including Trough, but the `_classify()` function has no code path that returns `"Trough"`. The `PHASE_COLORS` and `PHASE_EMOJIS` dicts include it, but it is dead code. This means a post-recession recovery with rising LEI, falling unemployment, and low probability will be classified as "Early Expansion" — which is approximately correct but loses the distinction between initial trough bounce (buy signal) and sustained expansion.

2. **Priority order bug at prob = 30–50%.** The Late Expansion branch triggers at `prob > 30`. The Peak branches trigger at `prob > 50`. This means there is no path to Peak if LEI is *not* negative and prob is, say, 48% — the model will fall through to Late Expansion (with LEI-inversion confirmer absent). In a slow-burn deterioration scenario where the yield curve is deeply inverted but LEI hasn't gone negative yet, the model will understate cycle risk.

3. **The Early Expansion branch at `prob < 20`** fires *before* the Mid Expansion branch at `prob < 30`. This means if `prob` is 18% and `lei_positive` is False and `lei_negative` is False (e.g., LEI is flat), the model returns Early Expansion with Low confidence — but 18% probability with flat LEI is arguably more consistent with Mid Expansion.

4. **Most likely misclassification: Contraction → Early Expansion skip.** After a rapid recovery (like 2020), probability drops quickly while unemployment is still elevated but falling. The model can flip from Contraction (NBER flag active) to Early Expansion in a single month once the NBER flag clears. There is no inertia or minimum-duration requirement. Adding a minimum 2-month holding period in Contraction before transitioning would reduce churn.

5. **LEI availability dependency.** The classifier requires `lei_growth` as an explicit parameter — but `compute_lei_growth()` uses `USSLIND` (Conference Board LEI), which has a monthly update cadence and 3–4 week lag. If this data is stale, `lei_growth` will be `None`, and the model will use `lei_positive = False` and `lei_negative = False`. This silently collapses three possible LEI states into one, without triggering the data quality cap (because LEI is not a `FeatureContribution` in the model output — it enters only as a scalar to the classifier). This is a data quality gap.

### System B (components/cycle_engine.py) — Logic Assessment

**Strengths:**
- The weighted vote approach (summing per-indicator phase scores) is more gradual and less susceptible to cliff-edge transitions than the probability threshold cascades in System A.
- Using T10Y2Y (not T10Y3M) for the cycle engine is appropriate — the 10Y–2Y is the academically preferred curve for cycle phase identification (though 10Y–3M is better for recession *probability*).
- The confidence calculation (winner / (winner + runner-up)) is a clean, interpretable metric.

**Weaknesses:**
- The yield curve scoring assigns 3.0 to Contraction when `latest < -0.75` — but a steep inversion during an active Fed tightening cycle without labor market deterioration is not the same as a contraction. There is no conditioning on unemployment or claims, so the yield curve alone can dominate the score to Contraction even if all other indicators say Mid Expansion.
- The INDPRO YoY thresholds (YoY < 0 → Contraction signal; YoY 2–5% → Mid Expansion) are applied symmetrically, but manufacturing cycles can diverge from service-sector cycles for 12+ months. A manufacturing recession (INDPRO negative) while services expand is not "Contraction" for the overall economy — and this model would call it that.
- CPI's role is unusual — high inflation is assigned to Late/Peak, but late-cycle *disinflation* (inflation falling from a high level) is indistinguishable in the current scoring from Early/Recovery. The 3-month trend check helps but does not fully resolve the ambiguity.
- The `confidence = winner / (winner + runner_up) * 100` formula has no lower bound per phase — if Contraction scores 6.0 and Late/Peak scores 5.9, confidence is `6/11.9 = 50%`, which reads as "Moderate." This is technically correct but will feel low to users who see two numbers nearly tied. Consider showing both the score differential and the confidence metric.

### Guard Against Misclassification

1. **Reconcile System A and System B.** Pick one authoritative cycle phase signal. Suggested: make System A (recession_model → cycle_classifier pipeline) the canonical source; use System B (`cycle_engine.py`) only for the indicators-breakdown panel. Document this in comments.

2. **Add transition dampening.** Require 2 consecutive months of a new phase signal before committing (debounce). This is especially important for the Contraction → Early Expansion transition.

3. **Fix the missing Trough state** in System A or remove it from PHASE_COLORS/PHASE_EMOJIS to eliminate dead code.

4. **Surface LEI staleness** in the data quality cap. Add LEI as a formal model input with a staleness flag, or pass a flag to `classify_cycle_phase()` when `lei_growth` is None due to data unavailability (not just missing because it's genuinely flat).

5. **Add a minimum recession duration filter.** If `nber_active` becomes True for fewer than 2 months and then clears, question whether the NBER signal is real or a data artifact.
