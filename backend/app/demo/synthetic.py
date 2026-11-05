"""SYNTHETIC demo documents and rulebook. No real bidder, tender, PAN, GST or financial data.

Three bidders are designed to exercise different paths:
- A: complete, compliant, clean text PDF.
- B: MSME (EMD exempt), turnover below threshold, expired ISO certificate, no GST certificate,
     and a technical page that leaks prices (must be withheld).
- C: scanned (image-only) CA certificate page, conflicting cross-section values, ambiguous date format.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pymupdf

TENDER_REF = "DEMO/ELEC/2026/001"
TENDER_TITLE = "Supply of 11 kV XLPE Aluminium Armoured Power Cable (SYNTHETIC DEMO)"
SPEC_TITLE = "Tender specification — DEMO/ELEC/2026/001 (synthetic)"

Page = list[str]


def _pdf(pages: list[Page], *, image_only: set[int] | None = None) -> bytes:
    image_only = image_only or set()
    doc = pymupdf.open()
    for idx, lines in enumerate(pages):
        page = doc.new_page(width=595, height=842)
        if idx in image_only:
            tmp = pymupdf.open()
            tp = tmp.new_page(width=595, height=842)
            _write(tp, lines)
            pix = tp.get_pixmap(matrix=pymupdf.Matrix(1.4, 1.4))
            page.insert_image(page.rect, pixmap=pix)
            tmp.close()
        else:
            _write(page, lines)
    data = bytes(doc.tobytes(garbage=3, deflate=True))
    doc.close()
    return data


def _write(page: pymupdf.Page, lines: Page) -> None:
    y = 60.0
    for line in lines:
        size = 13 if line.isupper() and len(line) < 70 else 10.5
        page.insert_text((50, y), line, fontsize=size, fontname="helv")
        y += size + 9


def tender_spec_pdf() -> bytes:
    return _pdf(
        [
            [
                "SYNTHETIC DEMONSTRATION DOCUMENT - NOT A REAL TENDER",
                "",
                TENDER_TITLE,
                f"Tender No. {TENDER_REF}",
                "Issued by: Demo Distribution Company (synthetic)",
                "",
                "Section 1. Instructions to bidders: submit one combined technical PDF and a separate sealed price bid.",
                "Price information shall not be included in the technical bid.",
            ],
            [
                "SECTION 2 - QUALIFYING REQUIREMENTS",
                "2.1 The bidder shall submit the Bidder Details Form (Annexure-1) duly filled.",
                "2.2 The bidder shall submit a copy of the PAN card and the GST registration certificate.",
                "2.3 Average annual turnover of the last three financial years shall not be less than Rs. 5 Crore,",
                "    certified by a Chartered Accountant with UDIN.",
                "2.4 The bidder shall hold a valid ISO 9001 certificate as on the bid submission deadline.",
            ],
            [
                "SECTION 3 - EARNEST MONEY DEPOSIT",
                "3.1 EMD of Rs. 2,00,000 shall be submitted. Bidders registered under MSME / Udyam for the",
                "    tendered item are exempted from EMD on submission of a valid registration certificate.",
                "3.2 The bidder shall submit the signed declaration (Annexure-5).",
            ],
            [
                "SECTION 4 - TECHNICAL SPECIFICATION",
                "4.1 Rated voltage: 11 kV (UE).",
                "4.2 Conductor material: Aluminium (H2/H4 grade).",
                "4.3 Nominal cross-sectional area of conductor: not less than 300 sq.mm.",
                "4.4 Type test reports shall be examined by the technical committee.",
            ],
        ]
    )


@dataclass(frozen=True)
class SyntheticBid:
    key: str
    legal_name: str
    email: str
    phone: str
    technical_pdf: bytes
    commercial_pdf: bytes
    quoted_total: str


def _price_pdf(name: str, total: str) -> bytes:
    return _pdf(
        [
            [
                "PRICE BID (SEALED COMMERCIAL ENVELOPE) - SYNTHETIC",
                f"Bidder: {name}",
                f"Tender: {TENDER_REF}",
                "Item: 11 kV 3C x 300 sq.mm XLPE Al armoured cable, 25 km",
                f"Total quoted price (inclusive of taxes): Rs. {total}",
            ]
        ]
    )


def _bidder_details(name: str, pan: str, gst: str, msme: str) -> Page:
    return [
        "ANNEXURE-1 BIDDER DETAILS FORM",
        f"Name of Bidder: {name}",
        "Registered Address: 12 Demo Industrial Estate",
        f"PAN: {pan}",
        f"GSTIN: {gst}",
        f"MSME Registered: {msme}",
        "Authorised Signatory: (signed)",
    ]


def bidder_a() -> SyntheticBid:
    name = "Shakti Cables Private Limited (Synthetic)"
    pages = [
        _bidder_details(name, "AAAAA0000A", "24AAAAA0000A1Z5", "No"),
        [
            "INCOME TAX DEPARTMENT",
            "PERMANENT ACCOUNT NUMBER CARD",
            f"Name: {name}",
            "Permanent Account Number: AAAAA0000A",
        ],
        [
            "GOODS AND SERVICES TAX",
            "GST REGISTRATION CERTIFICATE (FORM GST REG-06)",
            f"Legal Name: {name}",
            "GSTIN: 24AAAAA0000A1Z5",
        ],
        [
            "CHARTERED ACCOUNTANT CERTIFICATE",
            "TURNOVER CERTIFICATE",
            f"This is to certify that {name}",
            "Average Annual Turnover: Rs. 62.50 Crore",
            "UDIN: 26000000AAAAAA0000",
        ],
        [
            "CERTIFICATE OF REGISTRATION",
            "ISO 9001:2015 QUALITY MANAGEMENT SYSTEM",
            f"Organisation: {name}",
            "Valid Until: 31/03/2027",
        ],
        [
            "GUARANTEED TECHNICAL PARTICULARS",
            "TECHNICAL DATA SHEET - 11 kV XLPE CABLE",
            "Rated Voltage: 11 kV",
            "Conductor Material: Aluminium",
            "Nominal Cross Sectional Area: 300 sq.mm",
            "Insulation: XLPE",
        ],
        [
            "EMD RECEIPT",
            "EARNEST MONEY DEPOSIT",
            "EMD Amount: Rs. 2,00,000",
            "Mode: Online transfer (synthetic)",
        ],
        [
            "ANNEXURE-5 DECLARATION",
            "We hereby declare that the information furnished is true and correct.",
            "Signature and seal of bidder (signed)",
        ],
    ]
    return SyntheticBid(
        "A",
        name,
        "tenders@shakti-cables.example",
        "+91 79 0000 0001",
        _pdf(pages),
        _price_pdf(name, "4,85,00,000.00"),
        "48500000.00",
    )


def bidder_b() -> SyntheticBid:
    name = "Varun Electricals (Synthetic)"
    pages = [
        _bidder_details(name, "BBBBB1111B", "24BBBBB1111B1Z5", "Yes"),
        [
            "INCOME TAX DEPARTMENT",
            "PERMANENT ACCOUNT NUMBER CARD",
            f"Name: {name}",
            "Permanent Account Number: BBBBB1111B",
        ],
        [
            "CHARTERED ACCOUNTANT CERTIFICATE",
            "TURNOVER CERTIFICATE",
            f"This is to certify that {name}",
            "Average Annual Turnover: Rs. 3.20 Crore",
            "UDIN: 26000000BBBBBB1111",
        ],
        [
            "CERTIFICATE OF REGISTRATION",
            "ISO 9001:2015 QUALITY MANAGEMENT SYSTEM",
            f"Organisation: {name}",
            "Valid Until: 30 June 2025",
        ],
        [
            "GUARANTEED TECHNICAL PARTICULARS",
            "TECHNICAL DATA SHEET - 11 kV XLPE CABLE",
            "Rated Voltage: 11 kV",
            "Conductor Material: Aluminium",
            "Nominal Cross Sectional Area: 300 sq.mm",
        ],
        [
            "SCHEDULE OF RATES (INCLUDED IN TECHNICAL BID BY MISTAKE)",
            "Item 1 Unit rate per metre: Rs. 1,850",
            "Total bid value: Rs. 4,62,50,000",
        ],
        [
            "ANNEXURE-5 DECLARATION",
            "We hereby declare that the information furnished is true and correct.",
            "Signature and seal of bidder (signed)",
        ],
    ]
    return SyntheticBid(
        "B",
        name,
        "bids@varun-electricals.example",
        "+91 79 0000 0002",
        _pdf(pages),
        _price_pdf(name, "4,62,50,000.00"),
        "46250000.00",
    )


def bidder_c() -> SyntheticBid:
    name = "Rudra Power Products LLP (Synthetic)"
    pages = [
        _bidder_details(name, "CCCCC2222C", "24CCCCC2222C1Z5", "No"),
        [
            "INCOME TAX DEPARTMENT",
            "PERMANENT ACCOUNT NUMBER CARD",
            f"Name: {name}",
            "Permanent Account Number: CCCCC2222C",
        ],
        ["GOODS AND SERVICES TAX", "GST REGISTRATION CERTIFICATE (FORM GST REG-06)", f"Legal Name: {name}"],
        [
            "CHARTERED ACCOUNTANT CERTIFICATE",
            "TURNOVER CERTIFICATE (SCANNED COPY)",
            f"This is to certify that {name}",
            "Average Annual Turnover: Rs. 7.10 Crore",
            "UDIN: 26000000CCCCCC2222",
        ],
        [
            "CERTIFICATE OF REGISTRATION",
            "ISO 9001:2015 QUALITY MANAGEMENT SYSTEM",
            f"Organisation: {name}",
            "Valid Until: 05/04/2027",
        ],
        [
            "GUARANTEED TECHNICAL PARTICULARS",
            "TECHNICAL DATA SHEET - 11 kV XLPE CABLE",
            "Rated Voltage: 11 kV",
            "Conductor details: Aluminium",
            "Nominal Cross Sectional Area: 300 sq.mm",
        ],
        [
            "GUARANTEED TECHNICAL PARTICULARS (CONTINUED)",
            "Nominal Cross Sectional Area: 240 sq.mm",
            "Armour: Galvanised steel strip",
        ],
        ["EMD RECEIPT", "EARNEST MONEY DEPOSIT", "EMD Amount: Rs. 2,00,000"],
        ["ANNEXURE-5 DECLARATION", "We hereby declare that the information furnished is true and correct."],
    ]
    return SyntheticBid(
        "C",
        name,
        "office@rudra-power.example",
        "+91 79 0000 0003",
        _pdf(pages, image_only={3}),
        _price_pdf(name, "4,71,00,000.00"),
        "47100000.00",
    )


def all_bids() -> list[SyntheticBid]:
    return [bidder_a(), bidder_b(), bidder_c()]


def demo_rulebook(spec_artifact_id: uuid.UUID | None) -> dict[str, object]:
    def src(page: int, clause: str, quote: str) -> list[dict[str, object]]:
        return [
            {
                "artifact_id": str(spec_artifact_id) if spec_artifact_id else None,
                "document_title": SPEC_TITLE,
                "page": page,
                "clause": clause,
                "quote": quote,
            }
        ]

    return {
        "schema_version": "1.0",
        "fields": [
            {
                "field_key": "bidder_legal_name",
                "label": "Bidder legal name",
                "data_type": "string",
                "aliases": ["Name of Bidder", "Legal Name"],
                "doc_classes": ["bidder_details"],
                "critical": False,
            },
            {
                "field_key": "msme_registered",
                "label": "MSME / Udyam registered",
                "data_type": "boolean",
                "aliases": ["MSME Registered", "Udyam Registered"],
                "doc_classes": ["bidder_details"],
            },
            {
                "field_key": "annual_turnover",
                "label": "Average annual turnover",
                "data_type": "money",
                "aliases": ["Average Annual Turnover", "Annual Turnover"],
                "doc_classes": ["ca_certificate"],
            },
            {
                "field_key": "iso_valid_until",
                "label": "ISO 9001 certificate valid until",
                "data_type": "date",
                "aliases": ["Valid Until", "Valid up to", "Expiry Date"],
                "doc_classes": ["iso_certificate"],
            },
            {
                "field_key": "rated_voltage",
                "label": "Rated voltage",
                "data_type": "decimal",
                "unit": "kV",
                "aliases": ["Rated Voltage"],
                "doc_classes": ["technical_data_sheet"],
            },
            {
                "field_key": "conductor_material",
                "label": "Conductor material",
                "data_type": "string",
                "aliases": ["Conductor Material", "Conductor details", "Conductor type"],
                "doc_classes": ["technical_data_sheet"],
            },
            {
                "field_key": "conductor_cross_section",
                "label": "Nominal conductor cross-section",
                "data_type": "decimal",
                "unit": "mm2",
                "aliases": ["Nominal Cross Sectional Area", "Cross Sectional Area"],
                "doc_classes": ["technical_data_sheet"],
            },
            {
                "field_key": "emd_amount",
                "label": "EMD amount",
                "data_type": "money",
                "aliases": ["EMD Amount", "Earnest Money Deposit Amount"],
                "doc_classes": ["emd_receipt"],
            },
        ],
        "document_requirements": [
            {
                "doc_class": "bidder_details",
                "name": "Bidder Details Form (Annexure-1)",
                "keywords": ["bidder details form", "annexure-1"],
                "mandatory": True,
            },
            {
                "doc_class": "pan_card",
                "name": "PAN card",
                "keywords": ["permanent account number card", "income tax department"],
                "mandatory": True,
            },
            {
                "doc_class": "gst_certificate",
                "name": "GST registration certificate",
                "keywords": ["gst registration certificate", "goods and services tax", "form gst reg-06"],
                "mandatory": True,
            },
            {
                "doc_class": "ca_certificate",
                "name": "CA turnover certificate",
                "keywords": ["chartered accountant certificate", "turnover certificate", "udin"],
                "mandatory": True,
            },
            {
                "doc_class": "iso_certificate",
                "name": "ISO 9001 certificate",
                "keywords": ["iso 9001", "quality management system", "certificate of registration"],
                "mandatory": True,
            },
            {
                "doc_class": "technical_data_sheet",
                "name": "Guaranteed technical particulars",
                "keywords": ["guaranteed technical particulars", "technical data sheet"],
                "mandatory": True,
            },
            {
                "doc_class": "emd_receipt",
                "name": "EMD receipt (unless MSME exempt)",
                "keywords": ["emd receipt", "earnest money deposit"],
                "mandatory": False,
            },
            {
                "doc_class": "declaration",
                "name": "Declaration (Annexure-5)",
                "keywords": ["annexure-5 declaration", "we hereby declare"],
                "mandatory": True,
            },
        ],
        "criteria": [
            {
                "criterion_id": "ADM-BIDDER-DETAILS",
                "name": "Bidder Details Form submitted",
                "category": "administrative",
                "operator": "DOCUMENT_PRESENT",
                "doc_class": "bidder_details",
                "source_references": src(
                    2, "2.1", "The bidder shall submit the Bidder Details Form (Annexure-1)"
                ),
            },
            {
                "criterion_id": "ELG-PAN",
                "name": "PAN card submitted",
                "category": "eligibility",
                "operator": "DOCUMENT_PRESENT",
                "doc_class": "pan_card",
                "source_references": src(2, "2.2", "submit a copy of the PAN card"),
            },
            {
                "criterion_id": "ELG-GST",
                "name": "GST registration certificate submitted",
                "category": "eligibility",
                "operator": "DOCUMENT_PRESENT",
                "doc_class": "gst_certificate",
                "source_references": src(2, "2.2", "the GST registration certificate"),
            },
            {
                "criterion_id": "FIN-TURNOVER",
                "name": "Average annual turnover at least Rs. 5 Crore",
                "category": "financial_capacity",
                "operator": "GTE",
                "field_key": "annual_turnover",
                "expected": "50000000",
                "source_references": src(2, "2.3", "shall not be less than Rs. 5 Crore"),
            },
            {
                "criterion_id": "SUP-ISO-VALID",
                "name": "ISO 9001 certificate valid on submission deadline",
                "category": "supporting_document",
                "operator": "DATE_VALID_ON",
                "field_key": "iso_valid_until",
                "evaluation_date_basis": "SUBMISSION_DEADLINE",
                "source_references": src(
                    2, "2.4", "valid ISO 9001 certificate as on the bid submission deadline"
                ),
            },
            {
                "criterion_id": "ADM-EMD",
                "name": "EMD of Rs. 2,00,000 (MSME exempt)",
                "category": "administrative",
                "operator": "GTE",
                "field_key": "emd_amount",
                "expected": "200000",
                "applies_if": {
                    "field_key": "msme_registered",
                    "operator": "EQ",
                    "value": False,
                    "if_unknown": "REVIEW",
                },
                "interpretation": "officer_defined",
                "source_references": src(
                    3, "3.1", "EMD of Rs. 2,00,000 shall be submitted ... MSME ... exempted"
                ),
            },
            {
                "criterion_id": "DEC-ANNEXURE-5",
                "name": "Signed declaration submitted",
                "category": "declaration",
                "operator": "DOCUMENT_PRESENT",
                "doc_class": "declaration",
                "source_references": src(3, "3.2", "submit the signed declaration (Annexure-5)"),
            },
            {
                "criterion_id": "TECH-VOLTAGE",
                "name": "Rated voltage 11 kV",
                "category": "technical",
                "operator": "EQ",
                "field_key": "rated_voltage",
                "expected": "11",
                "source_references": src(4, "4.1", "Rated voltage: 11 kV (UE)"),
            },
            {
                "criterion_id": "TECH-CONDUCTOR",
                "name": "Conductor material Aluminium",
                "category": "technical",
                "operator": "IN",
                "field_key": "conductor_material",
                "expected": ["Aluminium"],
                "source_references": src(4, "4.2", "Conductor material: Aluminium"),
            },
            {
                "criterion_id": "TECH-CROSS-SECTION",
                "name": "Cross-section not less than 300 sq.mm",
                "category": "technical",
                "operator": "GTE",
                "field_key": "conductor_cross_section",
                "expected": "300",
                "source_references": src(4, "4.3", "not less than 300 sq.mm"),
            },
            {
                "criterion_id": "TECH-TYPE-TEST",
                "name": "Type test reports examined by committee",
                "category": "technical",
                "operator": "MANUAL_REVIEW_REQUIRED",
                "source_references": src(
                    4, "4.4", "Type test reports shall be examined by the technical committee"
                ),
            },
        ],
    }
