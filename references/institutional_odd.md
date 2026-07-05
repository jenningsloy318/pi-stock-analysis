# Operational Due Diligence (ODD) Checklists

Use these checklists when executing Stage 7.7. Score each area as Pass / Caution / Fail. A Fail in any area downgrades the overall risk assessment by at least 1 level.

## Cybersecurity Posture

- [ ] History of data breaches: count, severity (records exposed), remediation time
- [ ] Security certifications: SOC 2 Type II, ISO 27001, FedRAMP, PCI DSS — which are current?
- [ ] CISO reporting structure: to CEO/Board (strong) vs. to CIO/CTO (weaker independence)
- [ ] Cyber insurance coverage: limits relative to potential breach costs
- [ ] Third-party security assessments: penetration test frequency, bug bounty program
- [ ] Incident response plan: last tested? Tabletop exercise frequency?

## Legal & Regulatory History

- [ ] Material litigation (past 5 years): class actions, IP disputes, employment suits, environmental penalties
- [ ] Pattern analysis: Are legal issues recurring (systemic) or one-off events?
- [ ] Regulatory enforcement actions: SEC, FTC, DOJ, EU Commission, state AG — settlements, consent decrees, ongoing investigations
- [ ] SEC comment letters: frequency, topics, resolution — pattern of aggressive accounting?
- [ ] FCPA / Anti-corruption: operations in high-risk jurisdictions, compliance program maturity
- [ ] Product liability: recall history, warranty reserve adequacy (% of revenue)

## Disaster Recovery & Business Continuity

- [ ] Documented DR/BC plan: yes/no, last updated, last tested
- [ ] Geographic redundancy: Are critical operations replicated across geographically diverse sites?
- [ ] RTO (Recovery Time Objective) and RPO (Recovery Point Objective): published targets for critical systems
- [ ] Historical downtime: Any multi-hour outages in past 24 months? Root cause and remediation.
- [ ] Cloud dependency: Single cloud provider risk? Multi-cloud strategy?
- [ ] Key person dependency: Single points of failure in operations, technology, or relationships?

## Insurance Coverage

- [ ] D&O (Directors & Officers): coverage limits relative to market cap
- [ ] Key person insurance: if founder-led or heavily dependent on 1-2 executives
- [ ] Business interruption: coverage adequacy relative to quarterly revenue run rate
- [ ] Cyber insurance: coverage limits, exclusions, ransomware coverage
- [ ] General liability and property: adequacy for physical asset-heavy businesses

## Intellectual Property Protection

- [ ] Patent portfolio: total count, grant rate, geographic coverage, citation count (quality proxy)
- [ ] Trade secret protocols: non-compete enforceability, confidentiality agreements, access controls
- [ ] IP litigation posture: Are they typically plaintiff (defending IP) or defendant (accused of infringement)?
- [ ] Trademark protection: key brands registered in all major markets?
- [ ] Open source risk: If software company, what % of codebase is open source? Copyleft licenses?

## Regulatory Compliance Infrastructure

- [ ] Dedicated compliance team: size, reporting structure, budget trend
- [ ] Regulatory examination history: findings, remediation timeline, repeat findings?
- [ ] Whistleblower program: hotline, non-retaliation policy, investigation process
- [ ] Training programs: frequency, coverage, attestation tracking
- [ ] Regulatory horizon scanning: process for identifying and preparing for upcoming regulations

## Third-Party Risk Management

- [ ] Vendor due diligence program: maturity (ad-hoc → standardized → automated)
- [ ] Critical vendor concentration: % of vendors that are single-source
- [ ] Fourth-party risk: Are critical vendors' vendors assessed?
- [ ] Vendor incident history: Any service disruptions caused by vendor failures?
- [ ] Contractual protections: Right to audit, SLA penalties, termination rights

## Scoring Rubric

| Area | Pass | Caution | Fail |
|------|------|---------|------|
| Cybersecurity | No breaches >1K records in 3yr, certifications current, CISO reports to Board | Minor incidents, some certifications, CISO reports to CTO | Major breach in 2yr, no certifications, no dedicated security leadership |
| Legal/Regulatory | No material litigation, clean regulatory record | Ongoing litigation but manageable, minor regulatory issues | Class action or major enforcement action, pattern of violations |
| DR/BC | Tested DR plan, geographic redundancy, <4hr RTO | DR plan exists but stale, single geography | No DR plan, single site, history of extended outages |
| Insurance | Adequate coverage for all major risks | Coverage exists but limits may be insufficient | Gaps in critical coverage, self-insured for major risks |
| IP | Strong patent portfolio, active defense, no adverse rulings | Moderate portfolio, some challenges | Patent cliff approaching, adverse IP ruling, weak protection |
| Compliance | Dedicated team, clean exam history, robust program | Adequate team, minor findings remediated | Under-resourced, repeat findings, material weaknesses |
| 3rd Party | Mature program, vendor diversification, contractual protections | Program exists but manual, some concentration | No formal program, critical single-source dependencies |
