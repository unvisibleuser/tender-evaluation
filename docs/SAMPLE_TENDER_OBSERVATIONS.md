# Notes from the supplied sample tender documents

These notes are for architecture and demo planning, not a substitute for reading the full tender pack or approving its legal interpretation.

## KLTPS ME-308 — `ME-308.pdf`

Observed in the supplied document:
- KLTPS tender notice identifies supply of plumbing and carpentry materials for Civil Colony Maintenance.
- Technical bid PDF is requested in scanned PDF form (300 DPI or higher); price bid is to be submitted online on the n-procure portal.
- The notice describes tender fee and EMD handling, including physical submission of the fee/EMD cover in the stated process.
- The document says no financial bid information should be included in the technical bid.
- Technical bid includes bidder details, annexures, integrity pact, and price bid schedule reference.
- Eligibility/exemption conditions exist for tender fee/EMD and depend on bidder category and supporting registration/certification.
- The terms include item-specific requirements such as PAN, past experience, OEM authorization or purchase proof, ISI/standard make, delivery period, and item-specific technical conditions.
- TPIA/CA/Statutory Auditor certification requirements appear in the document for technical QR support, with conditions dependent on estimated tender value.

Implementation implication:
- Fee/EMD checks must be configurable and conditional, not one universal checklist.
- Item-level technical fields and bidder declarations should be extracted from the relevant annexures/schedules.
- Price data must be isolated from technical scrutiny.
- Certificate verification requirements must be represented as conditional rules.

## GETCO Jambuva — `Technical_bid.pdf` (JTC/26-27/n-175)

Observed in the supplied document:
- Tender is for 66 kV line erection work involving ACSR Panther conductor and D/C Panther tower; route length stated as 26.870 RKM for line-1.
- Online submission is described; tender fee, EMD, and Integrity Pact payment transaction slip requirements are specified.
- Tender fee, EMD, offer validity, time limit, and contractor registration class are stated in the tender notice.
- Technical and Qualification Requirement evaluation is based on original offer documents submitted by deadline.
- New/additional/substitute/replacement documents after deadline are restricted; clarifications are limited by the tender's stated conditions.
- Performance/completion certificates have prescribed issuer and content requirements.
- The technical bid includes financial-position certification and detailed technical data/specification sections.
- Price bid is opened online after technical scrutiny.

Implementation implication:
- Store clause-specific clarification rules and do not let the AI request missing new eligibility evidence.
- Extract experience evidence as structured data: work name, contract number/date, contractor, scope, contract/executed value, start/completion dates, completion status, and issuer.
- Engineering fields need units, tolerance/normalization policy, and source citations.
- Do not infer a combined score unless the tender gives a formula.

## GETCO Jambuva — `jambuva_circle(1).pdf` (JTC/2026-27/23)

Observed in the supplied document:
- This is a different tender and a different submission arrangement: two separate sealed envelopes, technical/post-qualification information and price bid.
- Price bids are opened for further commercial evaluation only for bidders assessed as substantially technically responsive.
- Tender validity and fee/EMD values differ from the other sample.

Implementation implication:
- The system must support physical/sealed-envelope and online/hybrid workflows, not only one online flow.
- Tender-specific opening gates and receipt channels must be configurable.

## GSECL commercial terms — `KLTPS_Comm__Terms_Cond_E-PROCUREMENT.pdf`

Observed in the supplied document:
- It is a 71-page commercial terms document with vendor registration and re-registration conditions, fee schedules, validity, and other commercial/e-procurement clauses.
- Registration validity and supporting documents can be criteria, but exact applicability depends on tender item, bidder type, location, and clause conditions.

Implementation implication:
- Rules need conditional applicability and dependencies, not merely flat required/not-required flags.
- Vendor registration should be modeled with validity period, registered unit/location, covered item/category, and applicability.

## Important limitation

The supplied files are not all the same tender pack. They represent different authorities/work types and different procurement processes. Do not merge all their criteria into one universal rulebook. For a live tender, load the complete tender pack and its corrigenda, then create a separate tender-specific rulebook.
