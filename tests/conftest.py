import pytest

from app.config import Settings
from app.llm import BaseProvider, StructuredResult

HOME_HTML = """<html><head><title>Kettle & Co - Small-batch kitchen tools</title>
<meta name="description" content="Kettle & Co sells small-batch kitchen tools online, shipped across the US."></head>
<body><nav><a href="/about">About</a><a href="/pages/faq">FAQ</a><a href="https://other.com/x">x</a></nav>
<h1>Kitchen tools made to last</h1><p>Shop over 200 products, from cast iron pans to ceramic mugs.</p>
<script>var x = 1;</script></body></html>"""
ABOUT_HTML = """<html><head><title>About</title></head><body><p>Founded in 2019 in Austin, Texas, Kettle & Co
is a team of 25 people. We are hiring a customer support lead to help our growing community.
Free returns within 30 days on every order, and our support team answers every message.</p></body></html>"""
FAQ_HTML = """<html><body><p>Questions about shipping, returns and order tracking? Our help center has answers.
Orders ship within 2 business days from our Austin warehouse to all 50 states.</p></body></html>"""


class FakeResponse:
    def __init__(self, status, text, ctype="text/html"):
        self.status_code, self.text, self.headers = status, text, {"content-type": ctype}


class FakeClient:
    """Stands in for httpx.Client: serves fixed pages, 404 for robots.txt."""
    def __init__(self, pages):
        self.pages, self.requested = pages, []

    def get(self, url):
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return FakeResponse(404, "")
        return FakeResponse(200, self.pages[url]) if url in self.pages else FakeResponse(404, "")


SITE = {"https://kettleandco.example": HOME_HTML, "https://kettleandco.example/about": ABOUT_HTML,
        "https://kettleandco.example/pages/faq": FAQ_HTML}


class ScriptedProvider(BaseProvider):
    """Returns queued structured results in order; records the prompts it received."""
    name = "scripted"

    def __init__(self, results):
        super().__init__("scripted-model", 1.0, 5.0, None)
        self.results, self.prompts = list(results), []

    def structured(self, system, user, name, schema, max_tokens=2000):
        self.prompts.append((name, user))
        data = self.results.pop(0)
        return StructuredResult(data, 1000, 200, self.cost(1000, 200))


PROFILE = {
    "company_name": "Kettle & Co", "one_liner": "Online store selling small-batch kitchen tools.",
    "segment": "d2c_ecommerce", "segment_reason": "Sells its own products online", "products": ["pans", "mugs"],
    "location": "Austin, Texas", "employees": 25, "annual_revenue_usd": None, "publicly_listed": None,
    "valuation_usd": None, "locations": None, "size_evidence": "a team of 25 people", "sells_ai_products": False,
    "ai_products_evidence": "none",
    "facts": [
        {"claim": "Sells over 200 kitchen products", "quote": "Shop over 200 products, from cast iron pans to ceramic mugs.", "source": "S1"},
        {"claim": "Hiring a customer support lead", "quote": "We are hiring a customer support lead to help our growing community.", "source": "S2"},
        {"claim": "Offers free 30-day returns", "quote": "Free returns within 30 days on every order", "source": "S2"},
        {"claim": "Raised $50M Series B", "quote": "Kettle & Co raised $50 million in Series B funding", "source": "S1"},
    ],
}

SCORE = {"criteria": [
    {"id": "sells_online", "answer": "yes", "fact_ids": ["F1"], "reason": "Sells 200+ products online"},
    {"id": "support_load", "answer": "yes", "fact_ids": ["F2", "F3"], "reason": "Hiring support; free returns"},
    {"id": "growth", "answer": "yes", "fact_ids": ["F4"], "reason": "Raised Series B"},
    {"id": "catalog", "answer": "yes", "fact_ids": ["F1"], "reason": "200+ products"},
    {"id": "size_fit", "answer": "yes", "fact_ids": [], "reason": "Small team"},
]}

GOOD_DRAFT = {
    "subject": "Support help while Kettle & Co hires",
    "body": ("Hi Kettle & Co team,\n\nI noticed you're hiring a customer support lead to help your growing community. "
             "With over 200 products and free 30-day returns, a lot of the questions coming in are probably about "
             "order status, returns and shipping times.\n\nI build AI support agents that answer those routine "
             "questions instantly and hand anything unusual to your team with a full summary. I recently built one "
             "that passed 24 of 24 test conversations with zero policy violations.\n\n"
             "Would a 15-minute call to explore this be worthwhile?"),
    "facts_used": ["F2", "F1"],
}
BAD_DRAFT = {"subject": "Revolutionize your support", "body": "Hi [Name], I hope this email finds you well.", "facts_used": ["F4"]}


@pytest.fixture
def settings(tmp_path):
    s = Settings()
    s.db_path = tmp_path / "leads.db"
    s.outputs_dir = tmp_path / "outputs"
    s.tavily_api_key = ""
    s.hubspot_token = ""
    s.google_service_account_file = ""
    s.google_sheet_id = ""
    return s