# Quant Bible → Biotech EV Training Pack
*Generated 2026-05-05. Advisory only. No production code changes.*
*Source: MIT Sloan Quant Bible concepts adapted for biotech catalyst investing.*
*All exercises are original. No verbatim interview questions copied.*

---

## Section 1: 20 Probability Drills for Biotech Catalysts

DRILL 1: [PDUFA]
Setup: A biotech company has submitted a new drug for PDUFA approval. The probability of the drug being approved on its first submission is 85%.
Question: What is the probability that the drug will be approved if it has already passed Phase 2?
Answer: 0.7 * 0.85 = 0.605 or 60.5%
Explanation: This question tests conditional probability, focusing on how past performance (Phase 2 success) influences future approval chances.

DRILL 2: [Phase 3 readout]
Setup: A drug has passed Phase 2 and is now in Phase 3 trials. The historical data shows that 40% of drugs advance from Phase 2 to Phase 3.
Question: If a drug passes Phase 3, what is the probability it will be approved?
Answer: 0.55 * 0.4 = 0.22 or 22%
Explanation: This question uses conditional probability to determine the likelihood of approval given that a drug has successfully completed Phase 3.

DRILL 3: [CRL]
Setup: A biotech company is preparing for a CRL (complete response letter) from the FDA. The historical data shows that 20% of drugs receive a CRL.
Question: If a drug receives a CRL, what is the probability it will be approved?
Answer: 1 - 0.2 = 0.8 or 80%
Explanation: This question tests conditional probability by calculating the likelihood of approval after receiving a CRL.

DRILL 4: [Advisory committee]
Setup: A drug has passed all clinical trials and is awaiting an advisory committee meeting. The historical data shows that 70% of drugs receive favorable recommendations from the advisory committee.
Question: If a drug receives a favorable recommendation, what is the probability it will be approved?
Answer: 1 - (1 - 0.7) = 0.7 or 70%
Explanation: This question uses conditional probability to determine the likelihood of approval given a favorable advisory committee recommendation.

DRILL 5: [PDUFA]
Setup: A biotech company has submitted a new drug for PDUFA approval. The probability of the drug being approved on its first submission is 85%.
Question: What is the probability that the drug will be rejected if it fails Phase 2?
Answer: 0.3 * (1 - 0.85) = 0.045 or 4.5%
Explanation: This question tests conditional probability, focusing on how past performance (Phase 2 failure) influences future rejection chances.

DRILL 6: [Phase 2 readout]
Setup: A drug has passed Phase 1 and is now in Phase 2 trials. The historical data shows that 30% of drugs advance from Phase 1 to Phase 2.
Question: If a drug passes Phase 2, what is the probability it will be rejected?
Answer: 1 - (0.4 * 0.3) = 0.88 or 88%
Explanation: This question uses conditional probability to determine the likelihood of rejection given that a drug has successfully completed Phase 2.

DRILL 7: [CRL]
Setup: A biotech company is preparing for a CRL (complete response letter) from the FDA. The historical data shows that 20% of drugs receive a CRL.
Question: If a drug receives a CRL, what is the probability it will be rejected?
Answer: 1 - 0.8 = 0.2 or 20%
Explanation: This question tests conditional probability by calculating the likelihood of rejection after receiving a CRL.

DRILL 8: [Advisory committee]
Setup: A drug has passed all clinical trials and is awaiting an advisory committee meeting. The historical data shows that 70% of drugs receive favorable recommendations from the advisory committee.
Question: If a drug receives a unfavorable recommendation, what is the probability it will be rejected?
Answer: 1 - 0.7 = 0.3 or 30%
Explanation: This question uses conditional probability to determine the likelihood of rejection given an unfavorable advisory committee recommendation.

DRILL 9: [PDUFA]
Setup: A biotech company has submitted a new drug for PDUFA approval. The probability of the drug being approved on its first submission is 85%.
Question: What is the variance in approval rates if we consider only Phase 2 and PDUFA?
Answer: (0.4 * 0.65) + (0.6 * 0.85) - (0.7 * 0.85) = 0.13 or 13%
Explanation: This question tests the concept of variance, showing how approval rates vary based on different stages of clinical development.

DRILL 10: [Phase 2 readout]
Setup: A drug has passed Phase 1 and is now in Phase 2 trials. The historical data shows that 30% of drugs advance from Phase 1 to Phase 2.
Question: What is the variance in approval rates if we consider only Phase 2 and PDUFA?
Answer: (0.4 * 0.65) + (0.6 * 0.85) - (0.7 * 0.85) = 0.13 or 13%
Explanation: This question tests the concept of variance, showing how approval rates vary based on different stages of clinical development.

DRILL 11: [Label Expansion]
Setup: A biotech company has a 60% chance of successfully expanding its label to include a new indication based on current data.
Question: If the company decides to expand the label and it fails, what is the probability that they would have succeeded if they had more time?
Answer: 0.4
Explanation: The base rate of successful label expansion is 60%, so the probability of failure is 40%.

DRILL 12: [Financing]
Setup: A biotech company needs $50 million in funding to advance its lead drug through Phase 3 trials.
Question: If the company has a 70% chance of raising this amount from existing investors, what is the probability that they will need to seek additional funding?
Answer: 0.3
Explanation: The probability of needing additional funding is the complement of successfully raising $50 million from existing investors.

DRILL 13: [Partnership]
Setup: A biotech company has a 30% chance of securing a Phase 2 partnership with a major pharma company.
Question: If they do not secure this partnership, what is the probability that they will still be able to raise $50 million through other means?
Answer: 0.8
Explanation: The base rate of raising $50 million from existing investors is 70%, so the probability of needing additional funding is 30%.

DRILL 14: [Trial Halt]
Setup: A biotech company's Phase 2 trial has a 5% chance of being halted due to safety concerns.
Question: If the trial is halted, what is the probability that it was halted due to efficacy issues?
Answer: 0.3
Explanation: The base rate of trial halts is 5%, and assuming half are due to safety and half due to efficacy, the probability of a halt being due to efficacy is 30%.

DRILL 15: [Competitor Readout]
Setup: A competitor announces positive results from their Phase 2 trial for a similar drug.
Question: If the biotech company's own Phase 2 trial has a 60% chance of success, what is the probability that it will fail after hearing the competitor's readout?
Answer: 0.4
Explanation: The base rate of successful trials is 60%, so the probability of failure is 40%.

DRILL 16: [Expected Value]
Setup: A biotech company has a 50% chance of raising $20 million from an equity round and a 50% chance of raising nothing.
Question: What is the expected value of this funding opportunity?
Answer: $10 million
Explanation: The expected value is calculated as (0.5 * $20 million) + (0.5 * $0) = $10 million.

DRILL 17: [Bayesian Updating]
Setup: A biotech company has a 60% chance of success in its Phase 3 trial based on interim data.
Question: If the interim data shows positive trends, what is the updated probability of success?
Answer: 0.8
Explanation: Bayesian updating adjusts the base rate based on new evidence, assuming the update increases the probability from 60% to 80%.

DRILL 18: [Sample-Size Traps]
Setup: A biotech company conducts a Phase 2 trial with 50 patients and observes no significant effects.
Question: What is the probability that the true effect size is zero if they had conducted a larger trial of 200 patients?
Answer: 0.9
Explanation: Larger sample sizes generally reduce the likelihood of false negatives, so the probability that the true effect size is zero decreases from 50% to 10%.

DRILL 19: [Correlated Outcomes]
Setup: A biotech company's Phase 2 trial and a competitor's Phase 2 trial are correlated due to using similar compounds.
Question: If the competitor's trial fails, what is the probability that the biotech company's trial will also fail?
Answer: 0.7
Explanation: Correlated outcomes increase the likelihood of both events occurring together, assuming a correlation coefficient of 0.5.

DRILL 20: [Label Expansion]
Setup: A biotech company has a 60% chance of successfully expanding its label to include a new indication based on current data.
Question: If the expansion is successful, what is the probability that it will be approved by regulatory authorities?
Answer: 0.8
Explanation: The base rate of label expansion approval is 80%, so the probability of success is 80%.

---

## Section 2: 10 EV / Calibration Exercises

EXERCISE 1: PDUFA Date Extension
Setup: Drug A, Phase 3, $500M market cap, PDUFA extension announced
Probability: 40% (Regulatory delays are common and can be unpredictable)
Upside: +20%
Downside: -30%
Position size: 10%
EV calculation: 0.4 * 20% - 0.6 * 30% = -2%
Decision: No-Go
Calibration note: The probability of a PDUFA extension is too high, as regulatory agencies typically aim to meet their deadlines.

EXERCISE 2: Phase 2 Readout Failure
Setup: Drug B, Phase 2, $150M market cap, Negative readout announced
Probability: 30% (Phase 2 failures are not uncommon)
Upside: +10%
Downside: -40%
Position size: 15%
EV calculation: 0.3 * 10% - 0.7 * 40% = -21%
Decision: No-Go
Calibration note: The market may overreact to a Phase 2 failure, leading to an overly pessimistic downside estimate.

EXERCISE 3: Label Expansion Rejected
Setup: Drug C, FDA approval, $50M market cap, Label expansion rejected
Probability: 40% (Label expansions can be denied by regulatory bodies)
Upside: +15%
Downside: -25%
Position size: 8%
EV calculation: 0.4 * 15% - 0.6 * 25% = -7%
Decision: No-Go
Calibration note: The probability of a label expansion rejection is too high, as regulatory bodies may have valid reasons for denying such requests.

EXERCISE 4: Phase 3 Readout Success
Setup: Drug D, Phase 3, $1 billion market cap, Positive readout announced
Probability: 75% (Positive Phase 3 results are highly likely)
Upside: +30%
Downside: -20%
Position size: 20%
EV calculation: 0.75 * 30% - 0.25 * 20% = 14%
Decision: Go
Calibration note: The market may overreact to a Phase 3 success, leading to an overly optimistic upside estimate.

EXERCISE 5: CRL Issued
Setup: Drug E, FDA approval, $300M market cap, CRL issued
Probability: 20% (CRLs can be issued for various reasons)
Upside: +10%
Downside: -40%
Position size: 12%
EV calculation: 0.2 * 10% - 0.8 * 40% = -26%
Decision: No-Go
Calibration note: The probability of a CRL is too high, as regulatory bodies typically aim to approve drugs unless there are significant safety concerns.

EXERCISE 6: Partnership Breakup
Setup: Drug F, $250M market cap, Key partnership terminated
Probability: 35% (Partnerships can be terminated due to various reasons)
Upside: +15%
Downside: -45%
Position size: 18%
EV calculation: 0.35 * 15% - 0.65 * 45% = -20%
Decision: No-Go
Calibration note: The probability of a partnership breakup is too high, as partnerships are often crucial for drug development.

EXERCISE 7: Advisory Committee Negative Vote
Setup: Drug G, FDA approval, $1 billion market cap, Advisory committee votes against approval
Probability: 30% (Advisory committees can reject drugs)
Upside: +25%
Downside: -40%
Position size: 16%
EV calculation: 0.3 * 25% - 0.7 * 40% = -8%
Decision: No-Go
Calibration note: The probability of a negative advisory committee vote is too high, as regulatory bodies typically aim to approve drugs unless there are significant safety concerns.

EXERCISE 8: Trial Halt Due to Safety Concerns
Setup: Drug H, Phase 3, $500M market cap, Trial halted due to safety issues
Probability: 25% (Safety concerns can halt trials)
Upside: +10%
Downside: -45%
Position size: 14%
EV calculation: 0.25 * 10% - 0.75 * 45% = -30%
Decision: No-Go
Calibration note: The probability of a trial halt is too high, as safety concerns can be raised during clinical trials.

EXERCISE 9: Competitor Readout Success
Setup: Drug I, Phase 2, $100M market cap, Competitor announces positive readout
Probability: 45% (Competitors often have similar drug candidates)
Upside: +15%
Downside: -30%
Position size: 17%
EV calculation: 0.45 * 15% - 0.55 * 30% = -8%
Decision: No-Go
Calibration note: The probability of a competitor's success is too high, as the market may already be pricing in their potential approval.

EXERCISE 10: Label Expansion Approved
Setup: Drug J, FDA approval, $200M market cap, Label expansion approved
Probability: 60%

---

## Section 3: 10 Signal-vs-Noise Mistake Examples

MISTAKE 1: Sparse sample
Screener failure mode: sparse sample
Bad inference: "This small Phase 2 study shows strong efficacy, indicating a high probability of success."
Why it is wrong: The study has only 30 patients, which is too small to draw meaningful conclusions. A power analysis reveals that this sample size would require a very large effect size to achieve statistical significance.
Safer interpretation: "This early Phase 2 trial shows promising results but requires confirmation in larger trials with more patients."
Catch artifact/test: Perform a power analysis and compare the observed effect size to what is statistically significant for the given sample size.

MISTAKE 2: Stale data
Screener failure mode: stale data
Bad inference: "The company's Phase 3 trial completed last year showed excellent efficacy, indicating a high probability of approval."
Why it is wrong: The data was collected over two years ago. Regulatory agencies now require more up-to-date safety and efficacy data.
Safer interpretation: "The company's most recent Phase 3 results from six months ago showed strong efficacy but need to be updated with the latest data before making a decision on approval."
Catch artifact/test: Cross-reference the trial completion date with the current regulatory requirements for approval.

MISTAKE 3: Post-hoc rationalization
Screener failure mode: post-hoc rationalization
Bad inference: "The competitor's Phase 2 readout showed only marginal efficacy, but their label expansion was approved."
Why it is wrong: The competitor likely used post-hoc analyses to justify the approval despite the lack of statistical significance.
Safer interpretation: "The competitor's label expansion approval appears premature given the marginal efficacy in Phase 2. Further data are needed before making a similar decision."
Catch artifact/test: Look for any post-hoc analyses or cherry-picked data points that were not part of the original study design.

MISTAKE 4: Lookahead leakage
Screener failure mode: lookahead leakage
Bad inference: "The company's Phase 3 trial showed strong efficacy, and their upcoming PDUFA date is in two weeks."
Why it is wrong: The company likely used lookahead information to influence patient recruitment or treatment decisions.
Safer interpretation: "The company's strong Phase 3 results are impressive but need to be validated without any lookahead advantages before making a decision on approval."
Catch artifact/test: Compare the trial timeline with the PDUFA date and look for any unusual activities that could indicate lookahead leakage.

MISTAKE 5: Duplicated catalyst
Screener failure mode: duplicated catalyst
Bad inference: "The company's Phase 3 trial showed strong efficacy, and their upcoming label expansion is a major catalyst."
Why it is wrong: The label expansion is likely already priced into the stock, making it an overvalued catalyst.
Safer interpretation: "The company's strong Phase 3 results are promising but should be evaluated separately from the label expansion, which may not be as impactful as initially thought."
Catch artifact/test: Compare the stock price movement before and after the label expansion announcement to see if there is any abnormal pricing action.

MISTAKE 6: Overfit signal
Screener failure mode: overfit signal
Bad inference: "The company's Phase 2 trial showed strong efficacy, indicating a high probability of success."
Why it is wrong: The study had only 30 patients and included several subgroups. This small sample size and multiple comparisons led to an overfit signal.
Safer interpretation: "This early Phase 2 trial shows promising results but requires confirmation in larger trials with more patients."
Catch artifact/test: Perform a Bonferroni correction or use other statistical methods to account for multiple comparisons and reduce the risk of overfitting.

MISTAKE 7: Market-cap confounder
Screener failure mode: market-cap confounder
Bad inference: "The company's Phase 2 trial showed strong efficacy, and their market cap has increased by 50% in the past year."
Why it is wrong: The market cap increase could be due to factors unrelated to the drug's performance, such as a successful partnership or favorable regulatory news.
Safer interpretation: "This early Phase 2 trial shows promising results but should not be evaluated solely based on market cap. Other factors, such as partnerships and regulatory progress, should also be considered."
Catch artifact/test: Compare the stock price movement with other relevant financial metrics to see if there is any abnormal pricing action.

MISTAKE 8: Financing overhang
Screener failure mode: financing overhang
Bad inference: "The company's Phase 2 trial showed strong efficacy, and their upcoming financing round is a major catalyst."
Why it is wrong: The financing round could be used to fund additional development or marketing efforts rather than improving the drug's performance.
Safer interpretation: "This early Phase 2 trial shows promising results but should be evaluated separately from the upcoming financing round. Other factors, such as the quality of the new investors and potential synergies, should also be considered."
Catch artifact/test: Compare the stock price movement before and after the financing announcement to see if there is any abnormal pricing action.

MISTAKE 9: Event-date uncertainty
Screener failure mode: event-date uncertainty
Bad inference: "The company's Phase 3 trial showed strong efficacy, and their upcoming PDUFA

---

## Section 4: Event-Probability Reasoning Checklist

**Catalyst Event Probability Reasoning Checklist for Biotech Investing**

---

### A. BASE RATE ANCHORING (3 items)
1. **Event Frequency**: Has this type of event occurred before in the company's history or within the industry? [ ]
2. **Industry Trends**: Is there a broader trend indicating increased likelihood of such events? [ ]
3. **Competitor Activity**: Are competitors showing similar activities that could influence the outcome? [ ]

### B. DATA FRESHNESS AND SOURCE RELIABILITY (4 items)
1. **Publication Date**: Is the data from a recent publication or update? [ ]
2. **Source Credibility**: Who is providing the information, and is their reputation trustworthy? [ ]
3. **Peer Review**: Does the information come with peer-reviewed validation or expert commentary? [ ]
4. **Consistency Across Sources**: Are multiple sources corroborating the same information? [ ]

### C. EVENT SPECIFICITY (4 items)
1. **Specificity of Data**: Is the data specific to the event in question, not just general industry news? [ ]
2. **Event Details**: Do we have all necessary details about the event (e.g., trial status, regulatory action)? [ ]
3. **Impact Scope**: How broadly will this event impact the company and its stakeholders? [ ]
4. **Timeline Clarity**: Is there a clear timeline for when the event might occur or be resolved? [ ]

### D. PROBABILITY CALIBRATION (4 items)
1. **Historical Outcomes**: What was the outcome of similar events in the past? [ ]
2. **Expert Opinions**: Do expert opinions align with the data and analysis? [ ]
3. **Scenario Analysis**: Have we considered various scenarios and their probabilities? [ ]
4. **Risk Factors**: Are there any known risk factors that could influence the event's likelihood or outcome? [ ]

### E. MARKET-IMPLIED EXPECTATION (4 items)
1. **Market Reaction**: Has the market already priced in the event, as evidenced by stock price movements? [ ]
2. **Investor Sentiment**: What is the current investor sentiment towards the company and its prospects? [ ]
3. **Analyst Consensus**: Do analysts have updated their forecasts or ratings based on this information? [ ]
4. **Valuation Adjustments**: Has the company's valuation adjusted in response to this event? [ ]

### F. DOWNSIDE ASYMMETRY AND LIQUIDITY (4 items)
1. **Downside Risk**: What are the potential downside risks associated with this event? [ ]
2. **Liquidity Impact**: How might this event affect market liquidity for the company's stock or other securities? [ ]
3. **Impact on Trading**: Will trading volume increase or decrease, and how will that impact pricing? [ ]
4. **Contingency Planning**: Do we have contingency plans in place to manage potential negative outcomes? [ ]

### G. FINANCING AND STRUCTURAL RISK (3 items)
1. **Financing Needs**: Does the event require additional financing, and is there sufficient liquidity available? [ ]
2. **Debt Structure**: How will this event affect the company's debt structure and interest obligations? [ ]
3. **Operational Impact**: Will the event impact the company’s operational capabilities or financial performance? [ ]

### H. POST-EVENT VALIDATION PLAN (3 items)
1. **Validation Strategy**: What steps will we take to validate the outcome of the event once it occurs? [ ]
2. **Performance Metrics**: How will we measure the success or failure of the event based on predefined metrics? [ ]
3. **Feedback Loop**: Will there be a feedback loop to adjust strategies based on post-event outcomes? [ ]

---

### GO / SHADOW / NO-GO DECISION RULE

- **GO**: All A-D sections pass, EV is positive, and liquidity is adequate.
- **SHADOW**: Borderline cases where one or two sections fail but the overall assessment remains cautiously optimistic.
- **NO-GO**: Base rate miss, data stale, or asymmetric downside risk that outweighs potential upside.

---

**EV Calculation Example:**

Assume a company has a current EV of $1 billion and is expected to receive positive news (e.g., Phase 3 readout) that could increase its EV by 20%

### Artifact Verification Addendum (F and H expanded)

### Section F (Downside Asymmetry and Liquidity)

- [ ] **ADV check:** Confirm 20d avg dollar volume > 5x intended position size.
- [ ] **Liquidity flag check:** Check `options_quality_composite` in snapshot for liquidity flag.
- [ ] **Straddle price availability:** Confirm straddle price is available and crush breakeven is calculated.
- [ ] **Reviewable artifact check:** Check `hard_queue_artifacts.json` for `reviewable=True` before sizing.

### Section H (Post-Event Validation Plan)

- [ ] **Pre-event probability record:** Record pre-event probability estimate in `catalyst_log` with artifact path cited.
- [ ] **Predicted vs Realized comparison:** After event, compare predicted vs realized outcomes in CRT resolution tracker.
- [ ] **Data integrity check:** Check `data_auditor` integrity_report for any post-event WARN on price data.
- [ ] **Calibration evidence update:** Update `calibration_evidence` ledger within 5 trading days.

---

