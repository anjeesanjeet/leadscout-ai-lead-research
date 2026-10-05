# LeadScout evaluation report

Model: `anthropic:claude-haiku-4-5-20251001`  |  Companies: 24  |  News search: on  |  Run: 2026-10-05T14:37:50+00:00

| Metric | Result |
|---|---|
| Companies researched | 24/24 (100%) |
| Segment accuracy | 96% |
| Facts verified against sources | 167/186 (90%) |
| Unverified facts blocked | 19 |
| Fit for outreach (drafted) | 12 (50%) |
| Realistic targets drafted | 65% of 17 |
| Large controls filtered out | 86% of 7 |
| Targets wrongly capped as large | 4 |
| Drafts passing checks first time / after retry | 75% / 100% |
| Cost per lead | $0.0242 |
| Time per lead, avg / p95 | 19.7s / 26.5s |
| Draft quality (LLM judge, 1-5) | 4.08 |

## By segment

| Segment | Companies | Segment accuracy | Avg fit score | Drafted |
|---|---|---|---|---|
| d2c_ecommerce | 8 | 100% | 7.1 | 6 |
| b2b_saas | 8 | 100% | 5.6 | 2 |
| agency | 8 | 88% | 6.4 | 4 |

## Per company

| Company | Segment | Expected size | Score | Status | Facts verified | Judge |
|---|---|---|---|---|---|---|
| Brooklinen | d2c_ecommerce | small_mid | 8.0 | ready_for_review | 7/8 | 5 |
| Bombas | d2c_ecommerce | large | 5.0 (capped) | not_a_fit | 7/8 |  |
| Caraway | d2c_ecommerce | small_mid | 9.0 | ready_for_review | 7/8 | 4 |
| Our Place | d2c_ecommerce | small_mid | 8.0 | ready_for_review | 8/8 | 4 |
| Ridge | d2c_ecommerce | small_mid | 7.0 | ready_for_review | 5/5 | 4 |
| Bombay Shaving Company | d2c_ecommerce | small_mid | 8.0 | ready_for_review | 7/8 | 4 |
| Gymshark | d2c_ecommerce | large | 7.0 | ready_for_review | 8/8 | 4 |
| Warby Parker | d2c_ecommerce | large | 5.0 (capped) | not_a_fit | 8/8 |  |
| lemlist | b2b_saas | small_mid | 5.0 (capped) | not_a_fit | 8/8 |  |
| Close | b2b_saas | small_mid | 5.0 (capped) | not_a_fit | 5/8 |  |
| Canny | b2b_saas | small_mid | 5.0 (capped) | not_a_fit | 5/8 |  |
| Userpilot | b2b_saas | small_mid | 5.0 (capped) | not_a_fit | 8/8 |  |
| Tally | b2b_saas | small_mid | 7.0 | ready_for_review | 4/8 | 4 |
| SavvyCal | b2b_saas | small_mid | 8.0 | ready_for_review | 7/8 | 4 |
| Notion | b2b_saas | large | 5.0 (capped) | not_a_fit | 7/8 |  |
| Zapier | b2b_saas | large | 5.0 (capped) | not_a_fit | 8/8 |  |
| Single Grain | agency | small_mid | 7.0 | ready_for_review | 8/8 | 4 |
| Directive | agency | small_mid | 8.0 | ready_for_review | 8/8 | 4 |
| NoGood | agency | small_mid | 5.0 | not_a_fit | 4/5 |  |
| Social Beat | agency | small_mid | 2.0 | not_a_fit | 8/8 |  |
| Ignite Visibility | agency | small_mid | 10.0 | ready_for_review | 8/8 | 4 |
| Disruptive Advertising | agency | small_mid | 9.0 | ready_for_review | 8/8 | 4 |
| Ogilvy | agency | large | 5.0 | not_a_fit | 7/8 |  |
| Publicis Sapient | b2b_saas (expected agency) | large | 5.0 (capped) | not_a_fit | 7/8 |  |
