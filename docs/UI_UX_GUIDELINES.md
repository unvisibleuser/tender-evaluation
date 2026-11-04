# UI/UX guidelines — formal government procurement portal

## Visual direction

- Formal, restrained, institutional.
- White/light neutral surfaces, navy/blue primary actions, grey secondary elements.
- Avoid gradients, glassmorphism, oversized illustrations, animated AI mascots, or consumer-chat styling.
- Use consistent typography, clear hierarchy, and dense but legible data tables.
- Use status text + icon; never rely on colour alone.

## Global shell

Header:
- Authority logo/emblem placeholder;
- product title: "Tender Scrutiny & Evaluation Portal";
- tender context and tender number;
- environment badge (Demo / Staging / Production);
- user identity, role, organization, logout.

Sidebar:
- Dashboard
- Tenders
- Rulebook & Criteria
- Bid Submissions
- Document Scrutiny
- Technical Evaluation
- Commercial Opening
- Commercial Evaluation
- Comparative Statement
- Officer Decisions
- Audit Trail
- Administration

## Tender workspace

Top summary:
- Tender ID, title, procuring authority, submission deadline, current stage.
- Stage timeline with timestamps.
- Rulebook version and approval status.
- Corrigendum count and last amendment.

Tabs:
- Overview
- Tender Documents
- Rulebook
- Bidders
- Technical Scrutiny
- Commercial (locked until opening)
- Comparative Statement
- Decisions
- Audit

## Rulebook builder

Three-pane layout:
1. Source PDF and page navigation.
2. Proposed criterion form.
3. Criteria list with status: Draft / Needs clarification / Approved.

Every criterion row shows source page/clause, category, stage, field, operator, threshold, mandatory flag, and review status. Officer must approve before publishing.

## Bid scrutiny workspace

Left: document tree and page thumbnails.
Center: PDF viewer with highlighted evidence region.
Right: extracted field, raw text, normalized value, confidence, rule result, reviewer actions.

Provide filters:
- Missing document
- Duly-filled check
- Unreadable
- Low confidence
- Conflicting values
- Expired/invalid supporting certificate
- Officer review pending

## Comparative views

- Technical: show only tender-defined criteria and factual metrics; filter/sort by pass status, criterion, or defined score.
- Commercial: hidden until opening; after opening sort by evaluated price and show price components.
- Combined: only when tender's published evaluation formula defines it. Show formula and calculation breakdown.

Never label a bidder "best" based on an AI-generated narrative. Use neutral "Rank 1 by [published method]" wording.

## Accessibility

- Keyboard navigable tables and dialogs.
- Visible focus ring.
- Semantic headings and labels.
- Sufficient contrast.
- Screen-reader labels for statuses and icons.
- Do not convey meaning by colour alone.
- Confirm destructive/irreversible actions.
