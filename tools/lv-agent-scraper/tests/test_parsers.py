"""Parser tests against synthetic fixtures.

The live directories are unreachable from CI (and blocked by this environment's
egress policy), so extraction is verified against fixtures that reproduce the
markup shapes the real pages use: JSON-LD, labeled tel: links, and a lead form
standing in for contact details.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from lv_agents.directories import ZillowDirectory, normalize_name  # noqa: E402
from lv_agents.enrich import PhoneClassifier  # noqa: E402
from lv_agents.http import is_bot_wall  # noqa: E402
from lv_agents.parsers import (  # noqa: E402
    is_plausible_agent_email,
    normalize_phone,
    parse_profile,
)

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text()


class TestNormalizePhone:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("(702) 555-0134", "(702) 555-0134"),
            ("702-555-0134", "(702) 555-0134"),
            ("702.555.0134", "(702) 555-0134"),
            ("+1 702 555 0134", "(702) 555-0134"),
            ("tel:+17025550134", "(702) 555-0134"),
        ],
    )
    def test_normalizes_common_formats(self, raw, expected):
        assert normalize_phone(raw) == expected

    @pytest.mark.parametrize("raw", ["", "not a phone", "702-055-0134", "123"])
    def test_rejects_invalid(self, raw):
        assert normalize_phone(raw) is None


class TestEmailFiltering:
    def test_rejects_platform_and_asset_addresses(self):
        assert not is_plausible_agent_email("support@zillow.com")
        assert not is_plausible_agent_email("logo@2x.png")

    def test_accepts_agent_address(self):
        assert is_plausible_agent_email("dana@desertsunrealty.test")


class TestParseProfile:
    def test_extracts_all_four_fields_when_labeled(self):
        profile = parse_profile(load("profile_labeled.html"))

        assert profile.name == "Dana Whitfield"
        assert profile.brokerage == "Desert Sun Realty"
        assert profile.email == "dana@desertsunrealty.test"
        assert profile.mobile_phone == "(702) 555-0134"
        assert profile.office_phone == "(702) 555-9900"

    def test_excludes_platform_email_from_footer(self):
        profile = parse_profile(load("profile_labeled.html"))
        assert "support@zillow.com" not in profile.emails

    def test_office_only_profile_yields_no_mobile_or_email(self):
        profile = parse_profile(load("profile_office_only.html"))

        assert profile.name == "Marcus Bellweather"
        assert profile.brokerage == "Redrock Property Group"
        assert profile.office_phone == "(702) 555-7788"
        assert profile.mobile_phone is None
        assert profile.email is None

    def test_handles_empty_input(self):
        profile = parse_profile("")
        assert profile.name is None
        assert profile.emails == []


class TestPhoneClassifier:
    def setup_method(self):
        self.classifier = PhoneClassifier()
        # Force heuristic mode so the test never depends on network credentials.
        self.classifier.account_sid = None
        self.classifier.auth_token = None

    def test_labeled_mobile_wins(self):
        number, kind = self.classifier.classify("(702) 555-0134", "(702) 555-9900", [])
        assert (number, kind) == ("(702) 555-0134", "labeled-mobile")

    def test_office_only_is_reported_as_office(self):
        number, kind = self.classifier.classify(None, "(702) 555-7788", [])
        assert (number, kind) == ("(702) 555-7788", "office")

    def test_unlabeled_distinct_from_office_is_direct(self):
        number, kind = self.classifier.classify(None, "(702) 555-7788", ["(702) 555-0134"])
        assert (number, kind) == ("(702) 555-0134", "direct-unlabeled")

    def test_no_numbers_is_none(self):
        assert self.classifier.classify(None, None, []) == (None, "none")


class TestDirectoryParsing:
    def test_extracts_profile_links_and_ranks(self):
        html = """
        <div>
          <a href="/profile/dana-whitfield/">Dana Whitfield</a>
          <a href="/profile/marcus-bell/">Marcus Bellweather</a>
          <a href="/profile/dana-whitfield/">Dana Whitfield</a>
          <a href="/homes/for_sale/">Not an agent</a>
        </div>
        """
        listings = ZillowDirectory(session=None, market_slug="las-vegas-nv").parse_listings(html, 0)

        assert [listing.name for listing in listings] == ["Dana Whitfield", "Marcus Bellweather"]
        assert [listing.rank for listing in listings] == [1, 2]
        assert listings[0].profile_url == "https://www.zillow.com/profile/dana-whitfield/"

    def test_pagination_url_shape(self):
        directory = ZillowDirectory(session=None, market_slug="las-vegas-nv")
        assert directory.page_url(1).endswith("/las-vegas-nv/")
        assert directory.page_url(3).endswith("?page=3")


class TestNormalizeName:
    def test_matches_same_agent_across_directories(self):
        assert normalize_name("Dana Whitfield, REALTOR®") == normalize_name("Dana Whitfield")

    def test_distinguishes_different_agents(self):
        assert normalize_name("Dana Whitfield") != normalize_name("Marcus Bellweather")


class TestBotWallDetection:
    def test_detects_perimeterx(self):
        assert is_bot_wall(200, "<html><div id='px-captcha'></div></html>")

    def test_detects_short_403(self):
        assert is_bot_wall(403, "denied")

    def test_allows_real_page(self):
        assert not is_bot_wall(200, "<html>" + "x" * 30000 + "</html>")
