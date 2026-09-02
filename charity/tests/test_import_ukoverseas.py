import os

import requests
import requests_mock
from django.test import TestCase

from charity.management.commands.import_ukoverseas import Command
from ftc.models import OrganisationClassification, Vocabulary, VocabularyEntries

FEED_URL = "https://raw.githubusercontent.com/jacksc09/uk-overseas-charities/main/feeds/findthatcharity/"
MOCK_FILES = (
    (FEED_URL + "sdg_vocabulary.csv", "ukoverseas_sdg_vocabulary.csv"),
    (FEED_URL + "engagement_vocabulary.csv", "ukoverseas_engagement_vocabulary.csv"),
    (FEED_URL + "classifications.csv", "ukoverseas_classifications.csv"),
)
ENTRY_COUNTS = (
    ("sdg_primary", 17),
    ("sdg_secondary", 17),
    ("overseas_engagement", 3),
)


class UKOverseasCommandTests(TestCase):
    databases = {"data", "admin"}

    def read_fixture(self, filename):
        dirname = os.path.dirname(__file__)
        with open(os.path.join(dirname, "fixtures", filename), "rb") as a:
            return a.read()

    def mock_csv_downloads(self, m):
        for url, filename in MOCK_FILES:
            m.get(url, content=self.read_fixture(filename))

    def get_codes(self, org_id, slug):
        return set(
            OrganisationClassification.objects.filter(
                org_id=org_id, vocabulary__vocabulary__slug=slug
            ).values_list("vocabulary__code", flat=True)
        )

    def assert_vocabulary_entries(self):
        for slug, expected in ENTRY_COUNTS:
            entries = VocabularyEntries.objects.filter(vocabulary__slug=slug)
            self.assertEqual(entries.count(), expected)
            self.assertEqual(entries.filter(current=True).count(), expected)

    def test_import(self):
        with requests_mock.Mocker() as m:
            self.mock_csv_downloads(m)
            Command().handle()

        self.assertEqual(
            dict(
                Vocabulary.objects.filter(
                    slug__in=["sdg_primary", "sdg_secondary", "overseas_engagement"]
                ).values_list("slug", "title")
            ),
            {
                "sdg_primary": "UN Sustainable Development Goal (primary)",
                "sdg_secondary": "UN Sustainable Development Goals (secondary)",
                "overseas_engagement": "Overseas engagement",
            },
        )
        self.assert_vocabulary_entries()
        self.assertEqual(
            VocabularyEntries.objects.get(
                vocabulary__slug="sdg_primary", code="1"
            ).title,
            "No Poverty",
        )
        self.assertEqual(
            VocabularyEntries.objects.get(
                vocabulary__slug="overseas_engagement", code="funds_partners_abroad"
            ).title,
            "Funds partners abroad",
        )

        classifications = OrganisationClassification.objects.filter(spider="ukoverseas")
        self.assertEqual(classifications.count(), 18)
        self.assertEqual(classifications.filter(source_id="ukoverseas").count(), 18)
        self.assertEqual(self.get_codes("GB-CHC-202918", "sdg_primary"), {"1"})
        self.assertEqual(self.get_codes("GB-CHC-202918", "sdg_secondary"), {"5", "10"})
        self.assertEqual(
            self.get_codes("GB-CHC-202918", "overseas_engagement"),
            {"operates_directly_abroad"},
        )
        self.assertEqual(self.get_codes("GB-CHC-1000944", "sdg_secondary"), set())

    def test_rerun_replaces_previous_records(self):
        with requests_mock.Mocker() as m:
            self.mock_csv_downloads(m)
            Command().handle()
            second = Command()
            second.handle()

        classifications = OrganisationClassification.objects.filter(spider="ukoverseas")
        self.assertEqual(classifications.count(), 18)
        self.assertEqual(classifications.filter(scrape_id=second.scrape.id).count(), 18)
        self.assert_vocabulary_entries()

    def test_missing_code_list_fails_loudly(self):
        with requests_mock.Mocker() as m:
            self.mock_csv_downloads(m)
            first = Command()
            first.handle()
            m.get(FEED_URL + "sdg_vocabulary.csv", status_code=404)
            with self.assertRaises(requests.HTTPError):
                Command().handle()

        classifications = OrganisationClassification.objects.filter(spider="ukoverseas")
        self.assertEqual(classifications.filter(scrape_id=first.scrape.id).count(), 18)
        self.assert_vocabulary_entries()

    def test_unknown_code_fails_loudly(self):
        classifications = (
            self.read_fixture("ukoverseas_classifications.csv")
            + b"GB-CHC-202918,sdg_primary,99,high\n"
        )
        with requests_mock.Mocker() as m:
            self.mock_csv_downloads(m)
            m.get(FEED_URL + "classifications.csv", content=classifications)
            scraper = Command()
            # save every row as it is read, so there are rows to roll back
            scraper.bulk_limit = 1
            with self.assertRaises(KeyError):
                scraper.handle()

        self.assertEqual(
            OrganisationClassification.objects.filter(spider="ukoverseas").count(), 0
        )
