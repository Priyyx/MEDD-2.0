"""Decision Support AI: every required question answers from the database with methodology."""
import re

import pytest

from app.ingestion.pipeline import process_file
from tests.conftest import copy_to_tmp, reset_production
from tests.fixtures import make_fixtures as mk

API = "/api/v1"


@pytest.fixture(scope="module", autouse=True)
def loaded(fixtures_dir):
    reset_production()
    assert process_file(copy_to_tmp(mk.synthetic(fixtures_dir, name="chat_set.xlsx", institutes=12, seed=3)),
                        "test")["status"].startswith("SUCCESS")


QUESTIONS = [
    ("What is the total equipment gap across Maharashtra?", "summary"),
    ("Which divisions have the highest equipment shortages?", "ranking:division:functional_shortfall"),
    ("Which institutes have the highest number of non-functional equipment?", "ranking:institute:non_functional"),
    ("What is the estimated procurement budget?", "budget"),
    ("Which departments require immediate procurement?", "priority"),
    ("What equipment is approaching its end-of-life period?", "ranking:equipment:end_of_life"),
    ("Which institutes have inadequate AMC/CMC coverage?", "amc"),
    ("Compare equipment availability between Pune and Nagpur", "compare:division"),
    ("Identify priority procurement requirements", "priority"),
    ("Top 10 net requirement by cost tier", "cost_tiers"),
]


@pytest.mark.parametrize("q,intent", QUESTIONS)
def test_required_questions(client, admin_h, q, intent):
    r = client.post(f"{API}/chat", headers=admin_h, json={"question": q}).json()
    assert r["intent"] == intent, r["intent"]
    assert r["methodology"] and "How this was calculated" in r["html"]
    assert r["mode"] == "deterministic"


def test_summary_numbers_match_kpi_engine(client, admin_h):
    s = client.get(f"{API}/kpis/summary", headers=admin_h).json()
    html = client.post(f"{API}/chat", headers=admin_h, json={"question": "overall summary"}).json()["html"]
    txt = re.sub("<[^>]+>", " ", html)
    def ind(n):  # Indian grouping as rendered
        s_ = str(n); h, t = s_[:-3], s_[-3:]
        parts = []
        while len(h) > 2:
            parts.insert(0, h[-2:]); h = h[:-2]
        if h:
            parts.insert(0, h)
        return (",".join(parts) + "," + t) if parts else t
    assert ind(s["required"]) in txt and ind(s["functional"]) in txt


def test_chat_respects_filters(client, admin_h):
    r = client.post(f"{API}/chat", headers=admin_h, json={"question": "summary", "filters": {"division": ["Nagpur"]}}).json()
    assert "Division: Nagpur" in r["scope"]


def test_unknown_question_gets_no_fabricated_numbers(client, admin_h):
    r = client.post(f"{API}/chat", headers=admin_h, json={"question": "what is the weather tomorrow"}).json()
    assert r["intent"] == "fallback" and not re.search(r"\d{3,}", re.sub("<[^>]+>", "", r["html"].split("<details")[0]))


def test_viewer_gets_no_budget(client):
    from tests.conftest import login
    h = login(client, "t_viewer")
    r = client.post(f"{API}/chat", headers=h, json={"question": "What is the estimated procurement budget?"}).json()
    assert "restricted" in r["html"]
