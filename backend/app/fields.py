"""Single source of truth for the DocuTrack record schema.

Every domain field lives here exactly once. The ORM (``models.py``), the RBAC
allow-lists (``rbac.py``), server-side validation (``validation.py``), and Excel
import/export all derive from this registry, so field names, sections, owning
roles, types and enum options can never drift apart.

Labels match the exact 120 column headers of the production workbook
``docutrack_records.xlsx`` (sheet "DocuTrack Records"), so import/export round-
trips losslessly. Enum option sets are taken verbatim from the prototype
``docutrack.html`` ``<select>`` elements. Domain values are stored in the
``records.data`` JSON column keyed by ``Field.key``; ``unit_code`` is also
promoted to a real, unique DB column.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dc_field
from enum import Enum


class Role(str, Enum):
    admin = "admin"
    document_compliance = "document_compliance"
    scanning = "scanning"
    filing = "filing"
    notary = "notary"


# Owner of a field = the role responsible for writing it (besides admin, who may
# write everything). "base" fields are set at record creation by admin or
# document_compliance and thereafter editable only by admin.
BASE = "base"


class FieldType(str, Enum):
    text = "text"
    longtext = "longtext"
    date = "date"
    email = "email"
    number = "number"
    integer = "integer"
    enum = "enum"


@dataclass(frozen=True)
class Field:
    key: str            # stable machine name, unique across the whole schema
    label: str          # exact production column header
    section: str        # logical group for the UI
    owner: str          # BASE or a Role value — who may write it
    type: FieldType = FieldType.text
    options: tuple[str, ...] = dc_field(default_factory=tuple)  # for enum


# --- Enum option sets (verbatim from docutrack.html) ------------------------
GEO = ("SOMA1", "SOMA2", "SOMA3", "NOMA1", "NOMA2")
UNIT_STATUS = ("Reserved", "Contracted", "Booked", "Fallout", "Backout", "Cancelled")
MODE_OF_PAYMENT = ("ADA", "spot cash", "PDC")
SPA_STATUS = ("N/A", "Pending Preparation", "For Signing", "Signed", "Released", "Notarized")
SPA_TYPE = ("NISPA", "CISPA", "APOSTILLE", "NSPA")
DOCKET_SCAN_STATUS = (
    "no docket/CPA yet", "pending scanning", "scanned - fallout", "scanned - backout",
    "scanned - cancelled", "scanned - w/ RDU", "scanned - complete", "fallout",
    "backout", "cancelled", "transferred", "rebooked",
)
FILE_STATUS = (
    "No Docket yet", "Archived", "For Archiving", "For Filing", "On File - Complete",
    "On File - W/ RDU", "On File - W/ Lacking",
)
DOAS_STATUS = ("Pending Notary", "Notarized")
ARCH_ACCOUNTS_STATUS = ("fallout", "backout", "cancelled")
BOI_ENTRY_STATUS = ("pending", "submitted")

D = Role.document_compliance
S = Role.scanning
N = Role.notary
F = Role.filing
T = FieldType


# --- The registry: 120 fields, in workbook column order --------------------
FIELDS: tuple[Field, ...] = (
    # 3.1 Unit & Project Information (base) — cols 0-16
    Field("unit_code", "Unit Code", "Unit & Project Info", BASE),
    Field("company", "Company", "Unit & Project Info", BASE),
    Field("geo", "Geo", "Unit & Project Info", BASE, T.enum, GEO),
    Field("project_name", "Project Name", "Unit & Project Info", BASE),
    Field("unit", "Unit", "Unit & Project Info", BASE),
    Field("type", "Type", "Unit & Project Info", BASE),
    Field("phase", "Phase", "Unit & Project Info", BASE),
    Field("sub_phase", "Sub Phase", "Unit & Project Info", BASE),
    Field("batch", "Batch", "Unit & Project Info", BASE),
    Field("unit_status", "Unit Status", "Unit & Project Info", BASE, T.enum, UNIT_STATUS),
    Field("reserved_date", "Reserved Date", "Unit & Project Info", BASE, T.date),
    Field("contracted_date", "Contracted Date", "Unit & Project Info", BASE, T.date),
    Field("booked_date", "Booked Date", "Unit & Project Info", BASE, T.date),
    Field("withdrawal_date", "Withdrawal Date", "Unit & Project Info", BASE, T.date),
    Field("bank_finance", "Bank Finance", "Unit & Project Info", BASE),
    Field("tcp", "TCP", "Unit & Project Info", BASE, T.number),
    Field("la", "LA", "Unit & Project Info", BASE, T.number),

    # 3.1 Buyer's Information (base) — cols 17-29
    Field("last_name", "Last Name", "Buyer's Info", BASE),
    Field("suffix", "Suffix", "Buyer's Info", BASE),
    Field("first_name", "First Name", "Buyer's Info", BASE),
    Field("middle_name", "Middle Name", "Buyer's Info", BASE),
    Field("citizenship", "Citizenship", "Buyer's Info", BASE),
    Field("civil_status", "Civil Status", "Buyer's Info", BASE),
    Field("gender", "Gender", "Buyer's Info", BASE),
    Field("employment", "Employment", "Buyer's Info", BASE),
    Field("contact_number", "Contact Number", "Buyer's Info", BASE),
    Field("email_principal", "Email Address of Principal Buyer", "Buyer's Info", BASE, T.email),
    Field("email_cobuyer", "Email Address of Co-buyer", "Buyer's Info", BASE, T.email),
    Field("address", "Address", "Buyer's Info", BASE, T.longtext),
    Field("buyer_remarks", "Remarks (Buyer)", "Buyer's Info", BASE, T.longtext),

    # 3.1 BOI Status (base) — col 30
    Field("boi_start_commercial_ops", "BOI Start of Commercial Operations", "BOI Status", BASE, T.date),

    # 3.2 Document Compliance — cols 31-53
    Field("doc_compliance_officer", "Doc Compliance Officer", "Compliance Team", D),
    Field("date_received_from_sas", "Date Received from SAS", "Compliance Team", D, T.date),
    Field("date_transmitted_to_scanning", "Date Transmitted to Scanning", "Compliance Team", D, T.date),
    Field("cleared_date", "Cleared Date", "Compliance Team", D, T.date),
    Field("account_location", "Account Location", "Compliance Team", D),
    Field("mode_of_payment", "Mode of Payment", "Compliance Team", D, T.enum, MODE_OF_PAYMENT),
    Field("pb_valid_id_primary", "PB Valid ID Primary", "Compliance Team", D),
    Field("pb_valid_id_secondary", "PB Valid ID Secondary", "Compliance Team", D),
    Field("sps_valid_id_primary", "SPS Valid ID Primary", "Compliance Team", D),
    Field("sps_valid_id_secondary", "SPS Valid ID Secondary", "Compliance Team", D),
    Field("cb1_valid_id_primary", "CB1 Valid ID Primary", "Compliance Team", D),
    Field("cb1_valid_id_secondary", "CB1 Valid ID Secondary", "Compliance Team", D),
    Field("cb2_valid_id_primary", "CB2 Valid ID Primary", "Compliance Team", D),
    Field("cb2_valid_id_secondary", "CB2 Valid ID Secondary", "Compliance Team", D),
    Field("aif_valid_id_primary", "AIF Valid ID Primary", "Compliance Team", D),
    Field("aif_valid_id_secondary", "AIF Valid ID Secondary", "Compliance Team", D),
    Field("lacking_remarks", "Lacking Remarks", "Compliance Team", D, T.longtext),
    Field("spa_status", "SPA Status", "Compliance Team", D, T.enum, SPA_STATUS),
    Field("spa_type", "SPA Type", "Compliance Team", D, T.enum, SPA_TYPE),
    Field("spa_no_copies", "SPA No. of Copies", "Compliance Team", D, T.integer),
    Field("date_transmitted_for_scanning", "Date Transmitted for Scanning", "Compliance Team", D, T.date),
    Field("spa_remarks", "SPA Remarks", "Compliance Team", D, T.longtext),
    Field("compliance_team_remarks", "Compliance Team Remarks", "Compliance Team", D, T.longtext),

    # 3.3 Scanning — cols 54-58
    Field("docket_scanning_status", "Docket Scanning Status", "Scanning", S, T.enum, DOCKET_SCAN_STATUS),
    Field("scanning_ao", "Scanning AO", "Scanning", S),
    Field("date_received_scanning", "Date Received (Scanning)", "Scanning", S, T.date),
    Field("date_scanned", "Date Scanned", "Scanning", S, T.date),
    Field("scanning_remarks", "Scanning Remarks", "Scanning", S, T.longtext),

    # 3.4 Notary — cols 59-65
    Field("notary_status", "Notary Status", "Notary Status", N),
    Field("notary_account_officer", "Account Officer", "Notary Status", N),
    Field("ncpa_notary_date", "NCPA Notary Date", "Notary Status", N, T.date),
    Field("endorsement_date", "Endorsement Date", "Notary Status", N, T.date),
    Field("ncpa_email_sent_date", "NCPA Email Sent Date", "Notary Status", N, T.date),
    Field("notarized_by", "Notarized By", "Notary Status", N),
    Field("notary_remarks", "Notary Remarks", "Notary Status", N, T.longtext),

    # 3.5 Filing System Entry — cols 66-69
    Field("filing_archiving_officer", "Filing & Archiving Officer", "Filing System Entry", F),
    Field("file_status", "File Status", "Filing System Entry", F, T.enum, FILE_STATUS),
    Field("date_filed", "Date Filed", "Filing System Entry", F, T.date),
    Field("filing_location", "Filing Location", "Filing System Entry", F),
    # Pullout Request — cols 70-76
    Field("pullout_requested_by", "Pullout — Requested By", "Pullout Request", F),
    Field("pullout_type_of_documents", "Pullout — Type of Documents", "Pullout Request", F),
    Field("pullout_requesting_dept", "Pullout — Requesting Dept/Group", "Pullout Request", F),
    Field("pullout_request_date", "Pullout — Request Date", "Pullout Request", F, T.date),
    Field("pullout_date_pullout", "Pullout — Date Pullout", "Pullout Request", F, T.date),
    Field("pullout_returned_docs", "Pullout — Returned Docs", "Pullout Request", F),
    Field("pullout_remarks", "Pullout — Remarks", "Pullout Request", F, T.longtext),
    # DOAS Notary Status — cols 77-82
    Field("doas_pullout_by", "DOAS — Pullout By", "DOAS Notary Status", F),
    Field("doas_requested_date_pullout", "DOAS — Requested Date Pullout", "DOAS Notary Status", F, T.date),
    Field("doas_status", "DOAS Status", "DOAS Notary Status", F, T.enum, DOAS_STATUS),
    Field("doas_ndoas_date_returned", "N-DOAS — Date Returned", "DOAS Notary Status", F, T.date),
    Field("doas_return_by", "DOAS — Return By", "DOAS Notary Status", F),
    Field("doas_remarks", "DOAS — Remarks", "DOAS Notary Status", F, T.longtext),
    # Archiving / Disposal — cols 83-88
    Field("arch_accounts_status", "Archiving — Accounts Status", "Archiving/Disposal", F, T.enum, ARCH_ACCOUNTS_STATUS),
    Field("arch_pullout_date", "Archiving — Pullout Date", "Archiving/Disposal", F, T.date),
    Field("arch_archived_date", "Archiving — Archived Date", "Archiving/Disposal", F, T.date),
    Field("arch_location", "Archiving — Location", "Archiving/Disposal", F),
    Field("arch_date_disposal", "Archiving — Date Disposal", "Archiving/Disposal", F, T.date),
    Field("arch_remarks", "Archiving — Remarks", "Archiving/Disposal", F, T.longtext),
    # BOI Status Entry — cols 89-92
    Field("boi_entry_status", "BOI Status Entry — BOI Status", "BOI Status Entry", F, T.enum, BOI_ENTRY_STATUS),
    Field("boi_entry_date_submitted", "BOI Status Entry — Date Submitted", "BOI Status Entry", F, T.date),
    Field("boi_entry_ncpa_submitted_to", "BOI Status Entry — NCPA Submitted To", "BOI Status Entry", F),
    Field("boi_entry_remarks", "BOI Status Entry — Remarks", "BOI Status Entry", F, T.longtext),

    # 3.2 Document Checklist (27 items, owned by Document Compliance) — cols 93-119
    Field("chk_buyers_info_sheet", "Document Checklist — Buyer's Info Sheet", "Document Checklist", D),
    Field("chk_cobuyer_info_sheet", "Document Checklist — Co-Buyer Info Sheet", "Document Checklist", D),
    Field("chk_computation_sheet", "Document Checklist — Computation Sheet", "Document Checklist", D),
    Field("chk_cpa", "Document Checklist — CPA", "Document Checklist", D),
    Field("chk_buyers_guide", "Document Checklist — Buyer's Guide", "Document Checklist", D),
    Field("chk_house_specs", "Document Checklist — House Specs", "Document Checklist", D),
    Field("chk_doas", "Document Checklist — DOAS", "Document Checklist", D),
    Field("chk_uhla", "Document Checklist — UHLA", "Document Checklist", D),
    Field("chk_cb_uhla", "Document Checklist — CB-UHLA", "Document Checklist", D),
    Field("chk_bir_1904", "Document Checklist — BIR 1904", "Document Checklist", D),
    Field("chk_bir_2316", "Document Checklist — BIR 2316", "Document Checklist", D),
    Field("chk_cb_1904", "Document Checklist — CB 1904", "Document Checklist", D),
    Field("chk_cb_bir_2316", "Document Checklist — CB BIR 2316", "Document Checklist", D),
    Field("chk_pb_cenomar", "Document Checklist — PB CENOMAR", "Document Checklist", D),
    Field("chk_cb_cenomar", "Document Checklist — CB CENOMAR", "Document Checklist", D),
    Field("chk_pb_marriage_certificate", "Document Checklist — PB Marriage Certificate", "Document Checklist", D),
    Field("chk_cb_marriage_certificate", "Document Checklist — CB Marriage Certificate", "Document Checklist", D),
    Field("chk_pb_coe", "Document Checklist — PB COE", "Document Checklist", D),
    Field("chk_cb_coe", "Document Checklist — CB COE", "Document Checklist", D),
    Field("chk_pb_payslip", "Document Checklist — PB Payslip", "Document Checklist", D),
    Field("chk_cb_payslip", "Document Checklist — CB Payslip", "Document Checklist", D),
    Field("chk_proof_of_billing", "Document Checklist — Proof of Billing", "Document Checklist", D),
    Field("chk_bank_statement", "Document Checklist — Bank Statement", "Document Checklist", D),
    Field("chk_annual_financial_statement", "Document Checklist — Annual Financial Statement", "Document Checklist", D),
    Field("chk_business_itr", "Document Checklist — Business ITR", "Document Checklist", D),
    Field("chk_dti_sec_cert", "Document Checklist — DTI / SEC Cert", "Document Checklist", D),
    Field("chk_exit_entry_stamp", "Document Checklist — Exit and Entry Stamp", "Document Checklist", D),
)


# --- Derived lookups --------------------------------------------------------
FIELDS_BY_KEY: dict[str, Field] = {f.key: f for f in FIELDS}
ALL_KEYS: frozenset[str] = frozenset(FIELDS_BY_KEY)
BASE_KEYS: frozenset[str] = frozenset(f.key for f in FIELDS if f.owner == BASE)


def keys_for_owner(owner) -> frozenset[str]:
    owner_val = owner.value if isinstance(owner, Role) else owner
    return frozenset(f.key for f in FIELDS if _owner_val(f.owner) == owner_val)


def _owner_val(owner) -> str:
    return owner.value if isinstance(owner, Role) else owner


def normalize_header(header: str) -> str:
    """Case/whitespace/punctuation-insensitive normalization for import matching.

    Mirrors the prototype's ``normalizeHeader``: lowercase and drop every
    non-alphanumeric character so "Unit Code", "unit_code", "UNIT-CODE" match.
    """
    return "".join(ch for ch in str(header).lower() if ch.isalnum())


# label (and key) -> canonical key, for import header matching
HEADER_LOOKUP: dict[str, str] = {}
for _f in FIELDS:
    HEADER_LOOKUP[normalize_header(_f.label)] = _f.key
    HEADER_LOOKUP[normalize_header(_f.key)] = _f.key
