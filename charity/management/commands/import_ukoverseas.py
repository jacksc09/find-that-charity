import csv
import io

import requests

from ftc.management.commands._base_scraper import CSVScraper
from ftc.models import OrganisationClassification, Vocabulary, VocabularyEntries

SDG_PRIMARY = "sdg_primary"
SDG_SECONDARY = "sdg_secondary"
OVERSEAS_ENGAGEMENT = "overseas_engagement"
FEED_URL = "https://raw.githubusercontent.com/jacksc09/uk-overseas-charities/main/feeds/findthatcharity/"


class Command(CSVScraper):
    name = "ukoverseas"
    allowed_domains = ["raw.githubusercontent.com"]
    start_urls = [FEED_URL + "classifications.csv"]
    source = {
        "title": "UK Overseas Charities: SDG and overseas engagement classifications",
        "description": "UN Sustainable Development Goal and overseas-engagement classifications for the England and Wales charities whose register entry lists an overseas country of operation, assigned by a large language model from register text and checked against a blind hand-labelled sample.",
        "identifier": "ukoverseas",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "license_name": "Creative Commons Zero v1.0 Universal (CC0 1.0)",
        "issued": "",
        "modified": "",
        "publisher": {
            "name": "Jack Chen",
            "website": "https://github.com/jacksc09/uk-overseas-charities",
        },
        "distribution": [
            {
                "downloadURL": "",
                "accessURL": "https://github.com/jacksc09/uk-overseas-charities/tree/main/feeds/findthatcharity",
                "title": "UK Overseas Charities - classification feed",
            }
        ],
    }
    vocab = {
        SDG_PRIMARY: {
            "title": "UN Sustainable Development Goal (primary)",
            "description": """The UN Sustainable Development Goal that best matches what the charity works on, assigned automatically by a large language model from the charity's own register text (name, activities and charitable objects), as part of the [UK Overseas Charities](https://github.com/jacksc09/uk-overseas-charities) project. In a blind hand-labelled sample of 150 charities the primary goal agreed with the human label 77.3% of the time (95% CI 70.0–83.3%), so individual tags may be incorrect. Only charities the register lists as operating overseas are covered. Wrong tags can be reported on the project's [issue tracker](https://github.com/jacksc09/uk-overseas-charities/issues/new).""",
            "code_url": FEED_URL + "sdg_vocabulary.csv",
            "vocab": None,
            "entries": {},
        },
        SDG_SECONDARY: {
            "title": "UN Sustainable Development Goals (secondary)",
            "description": """Up to two further UN Sustainable Development Goals for the charity's work, assigned automatically by a large language model from the charity's own register text (name, activities and charitable objects), as part of the [UK Overseas Charities](https://github.com/jacksc09/uk-overseas-charities) project. Read them as a short list of plausible goals rather than a ranking: in a blind hand-labelled sample of 150 charities the human's goal appeared among the charity's primary or secondary goals 94.0% of the time. Wrong tags can be reported on the project's [issue tracker](https://github.com/jacksc09/uk-overseas-charities/issues/new).""",
            "code_url": FEED_URL + "sdg_vocabulary.csv",
            "vocab": None,
            "entries": {},
        },
        OVERSEAS_ENGAGEMENT: {
            "title": "Overseas engagement",
            "description": """How the charity's money or activity reaches other countries, assigned automatically by a large language model from the charity's own register text (name, activities and charitable objects), as part of the [UK Overseas Charities](https://github.com/jacksc09/uk-overseas-charities) project. The three codes: **operates_directly_abroad** (the charity itself runs activities or has staff/projects in other countries), **funds_partners_abroad** (the charity mainly gives grants to or works through partner organisations overseas), and **uk_fundraising_only** (the charity raises money in the UK but its register text does not indicate that it operates or funds work abroad itself).

This flag is less reliable than the SDG tags: in a blind hand-labelled sample of 150 charities the three-way flag agreed with the human label 65.3% of the time (83.3%, 125/150, once the two overseas-active classes are merged — a post-hoc reading). The model over-calls overseas activity, so treat the boundary between "operates directly" and "funds partners" as soft, and treat "UK fundraising only" (92.7% precision) as the reliable signal. Wrong tags can be reported on the project's [issue tracker](https://github.com/jacksc09/uk-overseas-charities/issues/new).""",
            "code_url": FEED_URL + "engagement_vocabulary.csv",
            "vocab": None,
            "entries": {},
        },
    }
    models_to_delete = [OrganisationClassification]

    def run_scraper(self, *args, **options):
        # the code lists are fetched inside handle()'s transaction, so a
        # failed or malformed fetch leaves the previous run untouched
        self.fetch_vocabularies()
        super().run_scraper(*args, **options)

    def fetch_vocabularies(self):
        # the SDG code list serves both SDG vocabularies, so each code_url is
        # fetched once, but entries are created per vocabulary
        codes = {}
        for slug, v in self.vocab.items():
            self.logger.info("Fetching {}".format(v["title"]))
            v["entries"] = {}
            vocab, _ = Vocabulary.objects.update_or_create(
                slug=slug,
                defaults=dict(
                    title=v["title"],
                    description=v["description"],
                    single=False,
                ),
            )
            v["vocab"] = vocab
            VocabularyEntries.objects.filter(vocabulary=vocab).update(current=False)
            if v["code_url"] not in codes:
                codes[v["code_url"]] = list(
                    self.get_csv(v["code_url"], encoding="utf-8-sig")
                )
            for row in codes[v["code_url"]]:
                vocab_entry, _ = VocabularyEntries.objects.update_or_create(
                    vocabulary=vocab,
                    code=row["code"],
                    defaults={"title": row["title"], "current": True},
                )
                v["entries"][vocab_entry.code] = vocab_entry

    def parse_row(self, record):
        # an unknown vocabulary or code raises a KeyError on purpose: the run
        # is inside a transaction, so a malformed feed rolls back rather than
        # half-importing. The confidence column is not imported.
        entry = self.vocab[record["vocabulary"]]["entries"][record["code"]]
        self.add_record(
            OrganisationClassification,
            {
                "org_id": record["org_id"],
                "vocabulary_id": entry.id,
                "spider": self.name,
                "source": self.source,
                "scrape": self.scrape,
            },
        )

    def get_csv(self, url, encoding="utf8"):
        response = requests.get(url)
        response.raise_for_status()
        csv_text = response.content.decode(encoding)

        with io.StringIO(csv_text) as a:
            csvreader = csv.DictReader(a)
            for k, row in enumerate(csvreader):
                yield row
