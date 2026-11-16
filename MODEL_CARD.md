# Model card: Retail bank customer churn model

| | |
|---|---|
| **Model** | Gradient boosting classifier (scikit-learn `HistGradientBoostingClassifier`) inside a preprocessing pipeline |
| **Version** | 1.0 (portfolio project) |
| **Owner** | Renuka Khanzode (DataKritii) |
| **Output** | Probability that a customer leaves the bank (`Exited` = 1) |
| **Code** | `src/churn_model.py`; analysis in `notebooks/bank_churn_model_monitoring.ipynb` |

## Intended use

- **Use:** rank customers by churn risk so the retention team can decide whom to contact with an offer, and estimate what a campaign is worth.
- **Not for:** credit decisions, pricing, or any decision that withholds a product or service from a customer.
- **Users:** retention marketing and the model owner. Outputs are reviewed monthly (see *Monitoring*).

## Data

- *Churn Modelling* (Kaggle): 10,000 customers of a European retail bank in France, Germany and Spain; 20.4% churned. Amounts treated as euros.
- No missing values or duplicate customers. 36% of customers have a zero balance (a real state, kept as is).
- Split: 80% training (8,000) / 20% test (2,000), stratified by churn, `random_state = 42`.
- The data has no dates, so the churn window and an out-of-time test aren't available.

## Features

| Used | Not used |
|---|---|
| `Geography`, `NumOfProducts` (one-hot encoded; products treated as categories because churn isn't linear in them) | `Gender`, `Age`: protected grounds (see below) |
| `CreditScore`, `Tenure`, `Balance`, `HasCrCard`, `IsActiveMember`, `EstimatedSalary` | `Surname`, `CustomerId`, `RowNumber`: identifiers |

### Protected attributes

The Canadian Human Rights Act prohibits discrimination in services on grounds including sex and age. Both are excluded.
Measured cost (random forest, 5-fold CV AUC on the training set):

| Columns | CV AUC |
|---|---|
| All, including gender and age | 0.861 |
| Without gender | 0.858 |
| **Without gender and age (selected)** | **0.806** |

Gender adds almost nothing; age is a strong predictor. Re-introducing age for benefit-only offers would need compliance approval; the variant is documented and ready.
`Geography` (the country of the customer's branch) is kept; a validator should check it isn't acting as a proxy for national origin.

## Model selection

Four tuned candidates in identical pipelines. **Rule fixed in advance:** highest 5-fold cross-validated AUC; the test set is used once, after selection.

| Model | CV AUC | Test AUC | Test top-decile precision |
|---|---|---|---|
| Logistic regression | 0.781 | 0.764 | 63.5% |
| Decision tree (depth 5, min leaf 50) | 0.793 | 0.789 | 65.0% |
| Random forest (300 trees, min leaf 20) | 0.806 | 0.791 | 66.5% |
| **Gradient boosting (depth 3, learning rate 0.1)** | **0.808** | **0.797** | **66.5%** |

## Performance (test set, 2,000 customers)

- **AUC 0.797.** Top-decile precision **66.5%**, 3.3× the average churn rate of 20.3%.
- **Calibration:** average predicted churn 20.5% vs actual 20.3%; predicted and actual rates track closely across all ten deciles.
- **Main drivers (permutation importance):** number of products (by far), then balance, country and active membership.

These test values are the **development benchmarks** for monitoring.

## Fairness at development

Gender and age are not inputs, but outcomes were checked by group on the test set:

| Group | Predicted | Actual |
|---|---|---|
| Women | 20.9% | 25.1% |
| Men | 20.1% | 16.3% |
| Age 18–29 | 17.1% | 6.0% |
| Age 50–59 | 28.1% | 57.6% |

**The model under-predicts churn for women and for customers aged 40 and over**, most of all in their 50s, and over-predicts it for under-40s.
Fairness through unawareness doesn't equalise errors. Open decision for the business and compliance: add non-protected features that explain the gap,
set outreach rules by group, or approve a benefit-only use of age. Group calibration is reviewed monthly.

## Business use: retention economics (illustrative)

Offer cost €25, success rate 30%, customer value €500. Contacting a customer pays when p > 25 ÷ (0.30 × 500) = **16.7%**.
On the test set this means contacting 45% of customers and reaching 78% of churners. Expected value €26,089 vs realised €25,550, compared with €11,050 for contacting everyone.

## Monitoring

Monthly, on every scored month. Overall status = the worst of the five checks.

| Check | Amber above | Red above |
|---|---|---|
| AUC drop vs development (0.797) | 0.03 | 0.05 |
| Score PSI vs training scores | 0.10 | 0.25 |
| Calibration gap (absolute, actual − predicted) | 3 pts | 5 pts |
| Top-decile precision drop vs development (66.5%) | 5 pts | 10 pts |
| Largest input-feature PSI | 0.10 | 0.25 |

**Actions.** Amber: investigate within the month with the business. Red: alert model risk and the business; recalibrate or apply an overlay; retrain on recent data,
revalidate (including out-of-time) and redeploy through model governance.

Performance checks need outcomes, so in production they lag the drift checks by the churn window.

### Simulated production year (2025)

| Months | Status | What happened |
|---|---|---|
| Jan–Aug | Green | Normal noise (monthly AUC 0.776–0.820) |
| Sep | Amber | Country-mix drift: Geography PSI 0.13 |
| Oct | Red | Competitor event: calibration gap 5.5 pts, AUC 0.745 |
| Nov–Dec | Red | Calibration gap 10.1 and 13.5 pts; score PSI amber; IsActiveMember PSI 0.28 by December |

## Limitations

- One bank, one undated snapshot; the production year is simulated.
- Predicts *who will leave*, not *who the offer will keep*; an uplift model needs data from a randomised campaign.
- Economics are illustrative; real values would come from finance and past campaign results.
- Fairness gap for older customers and women (above).

## Reproducibility

`pip install -r requirements.txt`, then `python -m src.churn_model` regenerates every Power BI table; `pytest tests/` confirms the module matches the notebook.
