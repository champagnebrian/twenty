"""Incremental Google Sheets writer.

Rows are appended one at a time as each agent is resolved, so a crash mid-run
leaves everything found so far already persisted. Re-running resumes from the
profile URLs already present in the sheet.
"""

import logging

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

HEADER = [
    "Name",
    "Mobile Phone",
    "Email",
    "Brokerage",
    "Source Tier",
    "Profile URL",
    # Not in the requested column list, but the mobile/office/none breakdown
    # asked for in the report is only auditable if it is recorded per row.
    "Phone Type",
]


class SheetWriter:
    def __init__(self, credentials_path: str, title: str, share_with: list[str] | None = None) -> None:
        credentials = Credentials.from_service_account_file(credentials_path, scopes=SCOPES)
        self.client = gspread.authorize(credentials)
        self.service_account_email = getattr(credentials, "service_account_email", "unknown")
        self.title = title
        self.share_with = share_with or []
        self.worksheet: gspread.Worksheet | None = None

    def open_or_create(self) -> str:
        """Open the sheet by title, creating it if absent. Returns its URL."""
        try:
            spreadsheet = self.client.open(self.title)
            logger.info("opened existing sheet %r", self.title)
        except gspread.SpreadsheetNotFound:
            spreadsheet = self.client.create(self.title)
            logger.info("created sheet %r", self.title)

        for email in self.share_with:
            try:
                spreadsheet.share(email, perm_type="user", role="writer", notify=False)
                logger.info("shared sheet with %s", email)
            except gspread.exceptions.APIError as error:
                logger.warning("could not share with %s: %s", email, error)

        self.worksheet = spreadsheet.sheet1
        existing = self.worksheet.get_all_values()
        if not existing:
            self.worksheet.append_row(HEADER, value_input_option="RAW")
        elif existing[0] != HEADER:
            logger.warning("existing header differs from expected; appending anyway")

        return spreadsheet.url

    def already_written_urls(self) -> set[str]:
        """Profile URLs already in the sheet, used to resume an interrupted run."""
        if self.worksheet is None:
            return set()
        rows = self.worksheet.get_all_values()
        if len(rows) <= 1:
            return set()
        url_index = HEADER.index("Profile URL")
        return {row[url_index] for row in rows[1:] if len(row) > url_index and row[url_index]}

    def append_agent(self, record: dict) -> None:
        """Append one agent row. Called per agent, never batched."""
        if self.worksheet is None:
            raise RuntimeError("open_or_create() must be called first")
        row = [
            record.get("name") or "",
            record.get("mobile_phone") or "",
            record.get("email") or "",
            record.get("brokerage") or "",
            record.get("source_tier") or "",
            record.get("profile_url") or "",
            record.get("phone_type") or "none",
        ]
        self.worksheet.append_row(row, value_input_option="RAW")
