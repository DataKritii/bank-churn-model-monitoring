# Power BI build guide: Churn Model Monitoring

A step-by-step guide to building the Power BI monitoring report for this project, from the tables exported by the notebook.
Allow 4–6 hours. Save your work often (**Ctrl + S**).

**What you'll build:** a 6-page report that a model owner would review every month

| Page | Question it answers |
|---|---|
| 1. Model health | Is the model OK this month? Which checks failed, and when? |
| 2. Performance | Is the model still ranking and predicting well? |
| 3. Drift | Has the customer mix changed since the model was built? |
| 4. Fairness | Is the model equally accurate for different customer groups? |
| 5. Retention planner | Whom should we contact, and what is the campaign worth? (interactive what-if) |
| 6. Model card | What model is this, why was it chosen, and what are the rules? |

**Files in this folder**

| File | What it is |
|---|---|
| `data/months.csv` | One row per month (12): month start, label, scenario phase |
| `data/monitoring_monthly.csv` | One row per month: every monitoring metric and its status |
| `data/monitoring_status.csv` | One row per month × check (60): value and status, in the shape the status grid needs |
| `data/feature_drift.csv` | One row per month × feature (108): PSI vs the training data |
| `data/fairness_monthly.csv` | One row per month × group (120): predicted vs actual churn by gender, age band and country |
| `data/scored_customers.csv` | One row per scored customer per month (12,000): inputs, churn probability, risk band, outcome |
| `data/thresholds.csv` | One row per check (5): amber and red thresholds, and why the check exists |
| `data/model_comparison.csv` | One row per candidate model (4): cross-validated and test results |
| `DataKritii_theme.json` | Report theme in DataKritii colours |
| `measures.dax` | Every DAX measure, with its format |

> **Remember the story while you build.** Months 1–6 are stable. From month 7 the customer mix drifts (more German and inactive customers).
> In months 10–12 a competitor's savings account pulls away high-balance customers, a behaviour the model has never seen.
> Monitoring goes **amber in September** and **red from October**. Every page should help a reader see that.

---

## Part 1: Load the data

1. Open **Power BI Desktop** (free from the Microsoft Store).
2. **Home → Get data → Text/CSV**, choose `powerbi/data/scored_customers.csv`, then **Transform Data** (not Load). This opens Power Query.
3. Check the data types (the icon left of each column name). Change any that are wrong:

   | Column(s) | Type |
   |---|---|
   | `customer_id` | Text (it's an identifier, not a number to add up) |
   | `month_id`, `age`, `credit_score`, `tenure_years`, `products`, `has_credit_card`, `is_active_member`, `risk_band_order`, `flagged_top_decile`, `churned` | Whole number |
   | `balance`, `estimated_salary`, `churn_probability` | Decimal number |
   | `geography`, `gender`, `age_band`, `risk_band` | Text |

4. **Home → New Source → Text/CSV** and repeat for the other seven files. Check:
   - every `month_id`, `customers`, `check_order` and `status_rank` column is **Whole number**;
   - `months[month_start]` is **Date**;
   - all metric columns (`auc`, `psi`, `value`, `avg_predicted`, `amber_above`, `cv_auc`, …) are **Decimal number**;
   - `feature_drift[model_input]` and `model_comparison[selected]` are **True/False**.
5. **Home → Close & Apply.**

**Check:** in the Data view, `scored_customers` has 12,000 rows, `monitoring_status` 60 and `months` 12.

---

## Part 2: Build the data model

1. Open **Model view** (the third icon on the left).
2. Make sure exactly these six relationships exist, and delete any others Power BI created:

   | From (many) | To (one) | Cardinality | Cross-filter direction |
   |---|---|---|---|
   | `monitoring_monthly[month_id]` | `months[month_id]` | Many-to-one | Single |
   | `monitoring_status[month_id]` | `months[month_id]` | Many-to-one | Single |
   | `feature_drift[month_id]` | `months[month_id]` | Many-to-one | Single |
   | `fairness_monthly[month_id]` | `months[month_id]` | Many-to-one | Single |
   | `scored_customers[month_id]` | `months[month_id]` | Many-to-one | Single |
   | `monitoring_status[check]` | `thresholds[metric]` | Many-to-one | Single |

   Power BI may pick **One-to-one** for `monitoring_monthly`, because that table also has one row per month. Change it to **Many-to-one** and **Single**,
   so filters flow from `months` to the fact table only (two-way filters cause confusing results).
   `model_comparison` stays on its own: it describes the model, not a month.
3. **Sort columns** (Data view → select the column → **Column tools → Sort by column**):

   | Column | Sort by |
   |---|---|
   | `months[month_label]` | `month_id` (otherwise "Apr 2025" comes first) |
   | `monitoring_status[check]` | `check_order` |
   | `scored_customers[risk_band]` | `risk_band_order` (Low → Very high, not alphabetical) |

4. **Hide the ID and helper columns** from report view (right-click → Hide in report view): every `month_id` except the one in `months`, `check_order`,
   `status_rank`, `risk_band_order`. This keeps the field list clean and pushes everyone to the `months` table for dates.

The model is a **star schema**: `months` is the shared date dimension, so one month slicer filters every page.

---

## Part 3: Apply the theme and set up pages

1. **View → Themes → Browse for themes** → select `DataKritii_theme.json`. Pages get the ivory background and visuals get white cards.
2. Rename **Page 1** to `Model health`, and add five more pages: `Performance`, `Drift`, `Fairness`, `Retention planner`, `Model card`.
3. Keep the default page size (16:9).

**Colours used throughout**

| Meaning | Hex |
|---|---|
| Green status / good | `#2E7D5B` |
| Amber status / actual churn | `#D4A20B` |
| Red status / thresholds | `#B9603A` |
| Model and predictions (charcoal) | `#2C3E50` |
| Benchmarks and reference lines (grey) | `#95A5A6` |

---

## Part 4: Create the measures and What-if parameters

### 4a. The What-if parameters (for the Retention planner)

Create these first, because several measures use them. **Modeling → New parameter → Numeric range**, three times:

| Name | Data type | Minimum | Maximum | Increment | Default |
|---|---|---|---|---|---|
| `Offer Cost` | Whole number | 5 | 100 | 5 | 25 |
| `Success Rate` | Decimal number | 0.05 | 0.60 | 0.05 | 0.30 |
| `Customer Value` | Whole number | 100 | 2000 | 50 | 500 |

Leave **Add slicer to this page** ticked, and create them while you're on the **Retention planner** page (or cut and paste the slicers there later).
Each one creates a small table plus a measure named after it with "Value" on the end: `Offer Cost Value`, `Success Rate Value`, `Customer Value Value`.
Yes, the last one really is called that; leave the names as they are, because `measures.dax` uses them.

### 4b. The measures

1. **Home → Enter data**, name the table `_Measures`, and click **Load**.
2. Select `_Measures` in the Data pane, then **Home → New measure**.
3. Open `measures.dax` in Notepad. Copy **one** measure at a time, from the name to the end of its expression, for example
   ```
   Calibration Gap = [Actual Churn Rate] - [Avg Predicted Churn]
   ```
   Paste it into the formula bar and press **Enter**.
4. Set the format from the comment above each measure (**Measure tools → Format**). For the euro measures, choose **Custom** and type `€#,0;-€#,0`.
5. Repeat for every measure (skip the three commented-out What-if lines). Then delete the default `Column1` from `_Measures`.

**Key DAX ideas used here**
- **One row per month, so `AVERAGE` = "this month's value".** The monthly tables already hold each month's AUC and PSI. AUC can't be re-computed by adding up customers,
  which is why it was calculated in Python and only *displayed* in Power BI.
- **Worst status with `MAX`.** Statuses are stored as ranks (Green 1, Amber 2, Red 3), so `MAX` gives the worst one in any context: a cell, a month (= the overall status) or the year.
  `Status Color` turns that rank into a hex colour for conditional formatting.
- **Weighted averages with `SUMX`.** The fairness table stores a rate per month and group. Averaging rates would give every month equal weight regardless of size,
  so `Group Avg Predicted` multiplies each rate by its customer count, adds them up and divides by the total customers.
- **`VAR` for the what-if logic.** `Break-even Probability` is calculated once, stored in a variable, then used inside `FILTER`, so every customer is compared with the same cut-off.

**Check:** with no filters, a card showing `Customers` reads 12,000 and `Development AUC` reads 0.797.

---

## Part 5: Build the pages

The layout sketches show roughly where each visual goes.

### Page 1: Model health

```
┌──────────────────────────────────────────────────────────────────────┐
│ Churn model monitoring              [Month slicer: Dec 2025 ▾]       │
├────────────┬────────────┬────────────┬────────────┬────────────┬─────┤
│ Overall    │ AUC        │ Calibration│ Score PSI  │ Largest    │ Top │
│ status     │            │ gap        │            │ feature PSI│ 10% │
├────────────┴────────────┴────────────┴────────────┴────────────┴─────┤
│ Status grid: checks (rows) × months (columns), coloured by status     │
├──────────────────────────────────────┬───────────────────────────────┤
│ What happened (text box)             │ What we did (text box)        │
└──────────────────────────────────────┴───────────────────────────────┘
```

1. **Title:** Insert → Text box: *Churn model monitoring*. Underneath, smaller: *Gradient boosting churn model · 1,000 customers scored per month · Jan–Dec 2025 (simulated)*.
2. **Month slicer:** **Slicer** with `months[month_label]`. Format → Slicer settings → Style: **Dropdown**, Selection: **Single select**. Select **Dec 2025**.
3. **KPI cards:** six **Card** visuals with `Status Label` (rename it *Overall status*), `AUC`, `Calibration Gap`, `Score PSI`, `Largest Feature PSI` and `Top-Decile Precision`.
   - Colour the status card: select it → **Format → Callout value → Color → fx → Format style: Field value → What field: `Status Color`**.
     It turns red, amber or green with the selected month.
4. **Status grid:** **Matrix** visual.
   - Rows: `monitoring_status[check]`. Columns: `months[month_label]`. Values: `Status Label`.
   - **Format → Cell elements → Background color → fx → Format style: Field value → `Status Color`.** Set the values' font colour to white.
   - **Row subtotals: On**, and set the subtotal label to *Overall*. Because `Status Label` uses `MAX`, the subtotal row shows each month's worst status, which *is* the overall status.
   - Column subtotals: Off.
   - **Make the grid ignore the month slicer:** select the slicer → **Format → Edit interactions** → click the **None** icon on the matrix. The grid should always show the whole year.
5. **Text boxes:**
   > **What happened.** Months 1–8 were green. In **September**, the country mix drifted (more customers from Germany): amber. In **October**, a competitor's savings
   > account pulled away high-balance customers. Actual churn jumped above prediction and AUC fell: red.
   >
   > **What we did.** September: investigated the drift with the business. October: alerted model risk, applied a temporary recalibration and started retraining
   > on recent data. Redeployment goes through model governance with out-of-time validation.

**Check your numbers (Dec 2025):** Overall status Red · AUC 0.734 · Calibration gap 13.5% · Score PSI 0.174 · Largest feature PSI 0.279 · Top-decile precision 76.0%.
**Sep 2025:** Overall status Amber, with only *Largest input-feature PSI* amber in the grid.
**Grid:** 48 green, 6 amber and 6 red cells. The *Overall* row reads Green for Jan–Aug, Amber for Sep, and Red for Oct–Dec.
*Top-decile precision drop* stays green all year: see Page 2 for why that's a warning, not a comfort.

### Page 2: Performance

```
┌──────────────────────────────────────────────────────────────────────┐
│ Is the model still performing?                                        │
├──────────────────────────────────┬───────────────────────────────────┤
│ AUC by month, with development   │ Predicted vs actual churn by month│
│ benchmark and red line (line)    │ (line)                            │
├──────────────────────────────────┼───────────────────────────────────┤
│ Calibration gap by month         │ Top-decile precision vs           │
│ (columns, coloured by status)    │ development (line)                │
└──────────────────────────────────┴───────────────────────────────────┘
```

1. **AUC trend:** **Line chart**. X-axis `months[month_label]`; Y-axis `AUC`, `Development AUC`, `AUC Amber Line`, `AUC Red Line`.
   - Colours: `AUC` charcoal with markers; `Development AUC` grey, dashed; `AUC Amber Line` amber, dotted; `AUC Red Line` red, dotted (**Format → Lines → Series**).
   - Y-axis range: 0.70 to 0.84, so month-to-month movement is visible.
2. **Predicted vs actual:** **Line chart**. X-axis `month_label`; Y-axis `Avg Predicted Churn` (charcoal) and `Actual Churn Rate` (amber).
3. **Calibration gap:** **Clustered column chart**. X-axis `month_label`; Y-axis `Calibration Gap`.
   - **Format → Columns → Color → fx → Format style: Rules**, based on `Calibration Gap`:
     if value ≥ −1 and < 0.03 → green; ≥ 0.03 and < 0.05 → amber; ≥ 0.05 and ≤ 1 → red.
     (The thresholds apply to the *absolute* gap; here every month's gap above 3 points is positive, so these rules are enough.)
4. **Top-decile precision:** **Line chart**. X-axis `month_label`; Y-axis `Top-Decile Precision` (charcoal) and `Development Top-Decile Precision` (grey, dashed).
5. **Text box (bottom or side):**
   > Top-decile precision *rose* in Q4, because more customers were leaving overall. A dashboard showing only that metric would have looked healthy while the model was failing.

**Check your numbers:** Development AUC 0.797; AUC red line 0.747; AUC Dec 2025 0.734 (below the red line, as in Oct).
Dec 2025: predicted 25.9% vs actual 39.4%. Jan 2025: predicted 20.2% vs actual 20.1%. Development top-decile precision 66.5%.

### Page 3: Drift

```
┌──────────────────────────────────────────────────────────────────────┐
│ Has the customer mix changed?                                         │
├──────────────────────────────────┬───────────────────────────────────┤
│ Score PSI and largest feature    │ Risk-band mix by month            │
│ PSI by month, with thresholds    │ (100% stacked columns)            │
├──────────────────────────────────┴───────────────────────────────────┤
│ Feature drift heatmap: features (rows) × months (columns), PSI       │
└──────────────────────────────────────────────────────────────────────┘
```

1. **PSI trend:** **Line chart**. X-axis `month_label`; Y-axis `Score PSI` (charcoal) and `Largest Feature PSI` (amber).
   In the **Analytics pane** (magnifying glass icon) add two **Constant lines**: 0.10 (amber, dashed, label *Amber*) and 0.25 (red, dashed, label *Red*).
2. **Feature drift heatmap:** **Matrix**. Rows `feature_drift[feature]`; Columns `months[month_label]`; Values `Feature PSI`.
   - **Cell elements → Background color → fx → Format style: Gradient**, based on `Feature PSI`. Minimum: Number 0, white. Tick **Add a middle color**: Number 0.10, amber `#D4A20B`.
     Maximum: Number 0.25, red `#B9603A`.
   - Turn off row and column subtotals.
   - Note in the visual title that **Age is monitored but is not a model input**: it shows whether the population is changing, even though the model doesn't use it.
3. **Risk-band mix:** **100% stacked column chart**. X-axis `month_label`; Y-axis `Customers`; Legend `scored_customers[risk_band]`.
   Colours: Low green, Medium grey, High amber, Very high red.
4. **Text box:**
   > Feature drift gave the earliest warning: *Geography* passed 0.10 in September, two months before the score PSI did. The market event in October changed
   > *behaviour*, not the mix, so drift alone would not have caught it: that's why performance checks matter too.

**Check your numbers:** Score PSI Jan 0.013 → Dec 0.174. Heatmap: Geography 0.13 in Sep, 0.25 in Dec; IsActiveMember 0.28 in Dec (the only red cell);
NumOfProducts 0.00 all year. Risk-band mix, Jan → Dec: Very high 8.8% → 15.3%, Low 35.2% → 24.7%.

### Page 4: Fairness

```
┌──────────────────────────────────────────────────────────────────────┐
│ Is the model equally accurate for everyone?   [Dimension] [Months]   │
├──────────────────────────────────┬───────────────────────────────────┤
│ Predicted vs actual churn by     │ Calibration gap by group           │
│ group (clustered columns)        │ (columns)                          │
├──────────────────────────────────┴───────────────────────────────────┤
│ Table: group · customers · predicted · actual · gap · flag rate      │
├──────────────────────────────────────────────────────────────────────┤
│ What this means (text box)                                           │
└──────────────────────────────────────────────────────────────────────┘
```

1. **Dimension slicer:** `fairness_monthly[dimension]`, Style **Tile**, **Single select**. Select **Age band**.
   (Single select matters: with two dimensions selected the groups mix, e.g. "Female" next to "40–49".)
2. **Month slicer:** `months[month_label]`, Dropdown, multi-select, nothing selected (= all months).
3. **Predicted vs actual:** **Clustered column chart**. X-axis `fairness_monthly[group]`; Y-axis `Group Avg Predicted` (charcoal) and `Group Actual Churn` (amber).
4. **Calibration gap:** **Clustered column chart**. X-axis `group`; Y-axis `Group Calibration Gap`. Colour by rules: value ≥ 0.05 red, ≤ −0.05 grey, otherwise green.
5. **Table:** `group`, `Group Customers`, `Group Avg Predicted`, `Group Actual Churn`, `Group Calibration Gap`, `Group Flag Rate`.
6. **Text box:**
   > Gender and age are **not** model inputs (a fair-lending decision), but the model still under-predicts churn for women and for customers aged 40+, most of all in their 50s.
   > Removing a protected column doesn't make errors equal. Options: add non-protected features that explain the gap, set outreach rules by group,
   > or a compliance-approved use of age for benefit-only offers. This is reviewed monthly with compliance.

**Check your numbers (all months):**

| Dimension | Group | Customers | Predicted | Actual | Gap | Flag rate |
|---|---|---|---|---|---|---|
| Age band | 50–59 | 997 | 31.0% | 62.6% | 31.6% | 20.9% |
| Age band | 18–29 | 1,972 | 18.8% | 10.1% | −8.7% | 7.0% |
| Gender | Female | 5,603 | 23.3% | 29.6% | 6.4% | 12.1% |
| Gender | Male | 6,397 | 21.6% | 20.3% | −1.3% | 8.2% |
| Geography | Germany | 4,029 | 32.4% | 35.9% | 3.5% | 20.1% |

### Page 5: Retention planner

```
┌──────────────────────────────────────────────────────────────────────┐
│ Retention planner     [Offer Cost ●──] [Success Rate ●──] [Value ●──]│
│                       [Month slicer]                                  │
├───────────┬───────────┬───────────┬───────────┬───────────┬──────────┤
│ Break-even│ Customers │ Churners  │ Expected  │ Realised  │ Contact  │
│ prob.     │ to contact│ caught    │ value     │ value     │ everyone │
├───────────┴───────────┴───────────┴─────┬─────┴───────────┴──────────┤
│ Customers and churn rate by risk band   │ How the numbers work        │
│ (line and clustered column)             │ (text box)                  │
└─────────────────────────────────────────┴────────────────────────────┘
```

1. **Parameter slicers:** the three slicers from Part 4a. Make sure each shows a **single value** slider and is set to its default (25, 0.30, 500).
2. **Month slicer:** `months[month_label]`, Dropdown, multi-select, nothing selected.
3. **KPI cards:** `Break-even Probability`, `Customers to Contact` (add `Share Contacted` as a reference label, or use a second card), `Churners Caught`,
   `Expected Campaign Value`, `Realised Campaign Value`, `Value if Contact Everyone`. Add `Model Advantage` as a seventh card if there's room.
4. **Risk bands:** **Line and clustered column chart**. X-axis `scored_customers[risk_band]`; Column y-axis `Customers`; Line y-axis `Actual Churn Rate`.
5. **Text box** (the formula, step by step):
   > Contacting a customer is worth **p × success rate × customer value − offer cost**.
   > It pays when p is above **offer cost ÷ (success rate × customer value)** = 25 ÷ (0.30 × 500) = **16.7%** with the defaults.
   > *Expected* value uses the model's probabilities (what you'd budget with); *realised* value uses what actually happened.

**Check your numbers (defaults):**

| Months selected | Break-even | To contact | Share | Churners caught | Expected | Realised | Contact everyone |
|---|---|---|---|---|---|---|---|
| All 12 | 16.7% | 5,928 | 49.4% | 79.1% | €180,896 | €202,950 | €144,000 |
| Jan 2025 | 16.7% | 434 | 43.4% | 81.1% | €12,556 | €13,600 | €5,150 |
| Dec 2025 | 16.7% | 585 | 58.5% | 76.1% | €18,908 | €30,375 | €34,100 |

**Try it:** Jan 2025 with offer cost €40 → break-even 26.7%, 249 customers to contact, and contacting everyone loses money (−€9,850).

**The story in the December row:** when the model under-predicts, the *expected* value (€18.9K) badly understates what happened (€30.4K),
and contacting everyone (€34.1K) beats the model. A broken calibration breaks the campaign plan, which is exactly what monitoring is there to catch.

### Page 6: Model card

```
┌──────────────────────────────────────────────────────────────────────┐
│ About this model                                                     │
├──────────────────────────────────┬───────────────────────────────────┤
│ Model comparison (table)         │ Monitoring thresholds (table)     │
├──────────────────────────────────┴───────────────────────────────────┤
│ Key decisions (text box)                                             │
└──────────────────────────────────────────────────────────────────────┘
```

1. **Model comparison:** **Table** with `model_comparison[model]`, `cv_auc`, `test_auc`, `test_top_decile_precision`, `selected`.
   Set `cv_auc` and `test_auc` to 3 decimals. Highlight the selected row: **Cell elements → Background color → fx → Rules** on `selected`, or simply sort by `cv_auc` descending.
2. **Thresholds:** **Table** with `thresholds[metric]`, `amber_above`, `red_above`, `why`. Turn on **Word wrap** for `why`.
3. **Key decisions text box:**
   > - **Purpose:** rank customers by churn risk for retention offers. Not for credit decisions.
   > - **Data:** 10,000 customers of a European retail bank (Kaggle *Churn Modelling*). Train 80% / test 20%, stratified.
   > - **Excluded:** gender and age (fair lending). Cost: CV AUC 0.858 → 0.806.
   > - **Selection rule (fixed in advance):** highest 5-fold cross-validated AUC → gradient boosting (0.808).
   > - **Monitoring:** monthly; five checks with amber/red thresholds; overall status = worst check; fairness reviewed alongside.
   > - **Owner actions:** amber → investigate within the month; red → alert model risk, recalibrate or overlay, retrain and revalidate.
   > - Full documentation: `MODEL_CARD.md` in the GitHub repo.

---

## Part 6: Polish

1. **Page navigation:** Insert → Buttons → **Navigator → Page navigator**, at the top of every page.
2. **Sync the month slicer** between Model health and the other pages if you want one selection to carry across: **View → Sync slicers**.
   (Keep the Retention planner's month slicer separate; it's for exploring.)
3. **Tooltips:** on the status grid, add `monitoring_status[value]` and `thresholds[amber_above]` / `thresholds[red_above]` to **Tooltips**, so hovering a red cell shows the value and the threshold it broke.
4. **Consistent titles:** every visual gets a plain-language title that says what it shows, e.g. *Actual churn overtook prediction in October*.
5. **Alt text** (Format → General → Alt text) for each chart.
6. **Check every page** with Jan 2025, Sep 2025 and Dec 2025 selected.

---

## Part 7: Save and share

1. **Save** the report as `powerbi/bank_churn_monitoring.pbix`.
2. **Export a PDF:** File → Export → **Export to PDF**, saved as `powerbi/bank_churn_monitoring.pdf`. Select **Dec 2025** on page 1 first, so the PDF opens on the red month.
3. **Screenshots:** for each page, Windows key + Shift + S. Save them as `reports/figures/powerbi_1_health.png`, `powerbi_2_performance.png`, `powerbi_3_drift.png`,
   `powerbi_4_fairness.png`, `powerbi_5_retention.png`, `powerbi_6_model_card.png`.
4. **Walkthrough video (60–90 seconds):** click from Jan to Sep to Dec on page 1, then show the drift heatmap and move the What-if sliders.
   Good for the DataKritii YouTube channel and for the portfolio's "Watch the walkthrough" button.
5. **Commit and push:**
   ```bash
   git add .
   git commit -m "Add Power BI monitoring report, PDF export and screenshots"
   git push
   ```
6. In the project `README.md`, replace the placeholders under **Power BI report** with your screenshots.

---

## Interview checklist

You should be able to explain:
- What "owning" a model means beyond building it: documentation, monitoring, thresholds, actions, retraining
- Why gender and age were excluded, what it cost (CV AUC 0.858 → 0.806), and why the model is still less accurate for older customers
- How the champion model was chosen (a rule fixed in advance, test set used once)
- What each of the five checks detects, and why PSI uses 0.10 and 0.25
- Why drift checks warn early but performance checks confirm the damage, and why performance checks lag in real life (churn is only known after the outcome window)
- Why top-decile precision alone would have missed the problem
- The break-even formula, and why expected and realised value diverged in December
- What `MAX` over `status_rank`, `SUMX` weighting and the What-if parameters do in your measures
