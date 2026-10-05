"""The AI steps: profile extraction, fact verification (grounding), fit scoring and email drafting.

Design rule: the model proposes, code decides.
  * Every fact must carry a verbatim quote; code checks the quote really appears in the source text.
  * Fit scores are computed in code from per-criterion judgements, and a "yes" without verified evidence
    is downgraded to "unknown".
  * Drafts are checked in code (length, banned phrases, placeholders, verified facts only) and regenerated once.
"""
from __future__ import annotations

import re

from rapidfuzz import fuzz

from app.llm import BaseProvider

SEGMENTS = ["d2c_ecommerce", "b2b_saas", "agency", "other"]

# ---------------------------------------------------------------- 1. profile extraction

PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "company_name": {"type": "string"},
        "one_liner": {"type": "string", "description": "What the company does, in one plain sentence"},
        "segment": {"type": "string", "enum": SEGMENTS},
        "segment_reason": {"type": "string"},
        "products": {"type": "array", "items": {"type": "string"}, "maxItems": 6},
        "location": {"type": "string", "description": "Headquarters city/country if stated, else 'unknown'"},
        "employees": {"type": ["integer", "null"], "description": "Employee or team size if a source states it, else null"},
        "annual_revenue_usd": {"type": ["number", "null"],
                               "description": "Annual revenue in US dollars if stated, else null. Convert other currencies "
                                              "(1 crore INR is about $120,000; annualize monthly figures)."},
        "publicly_listed": {"type": ["boolean", "null"], "description": "true only if a source says it trades on a stock exchange"},
        "valuation_usd": {"type": ["number", "null"], "description": "Latest stated valuation in US dollars, else null"},
        "locations": {"type": ["integer", "null"], "description": "Number of offices or physical stores if stated, else null"},
        "size_evidence": {"type": "string", "description": "Verbatim text from the sources behind the size numbers, or 'not stated'"},
        "sells_ai_products": {"type": "boolean",
                              "description": "true only if the company's CORE product, the main thing it sells, is AI agents, "
                                             "AI assistants or AI automation. false for companies that sell other software, "
                                             "products or services and have added AI features to them."},
        "ai_products_evidence": {"type": "string", "description": "Verbatim text showing AI is the core product, or 'none'"},
        "facts": {
            "type": "array", "minItems": 1, "maxItems": 8,
            "items": {"type": "object", "properties": {
                "claim": {"type": "string", "description": "A short factual statement about the company"},
                "quote": {"type": "string", "description": "Verbatim text copied exactly from the source that proves the claim (max 30 words)"},
                "source": {"type": "string", "description": "Source label, e.g. S1"},
            }, "required": ["claim", "quote", "source"]},
        },
    },
    "required": ["company_name", "one_liner", "segment", "segment_reason", "products", "location", "employees",
                 "annual_revenue_usd", "publicly_listed", "valuation_usd", "locations", "size_evidence",
                 "sells_ai_products", "ai_products_evidence", "facts"],
}

PROFILE_SYSTEM = """You are a B2B research analyst. Build a factual company profile using ONLY the numbered sources.
Rules:
- Every fact needs a quote copied character-for-character from one source (no paraphrasing, max 30 words).
- Prefer specific, useful facts for sales outreach: products, customers, markets, recent launches, hiring, support setup.
- If something is not in the sources, do not include it. Use 'unknown' where asked.
- Size fields: copy only numbers the sources state (employees, revenue, valuation, locations). Use null when not
  stated. Community, user or customer counts are NOT employees. Never infer size from how famous a brand is.
- segment: d2c_ecommerce = sells its own PHYSICAL consumer products online; b2b_saas = sells software or online
  tools used by businesses or professionals, including freemium tools; agency = provides marketing, creative,
  technology or consulting services to client companies; other = anything else.
- sells_ai_products is about the core business only. Almost every company now has some AI features; that alone
  is false. Example: an email-outreach tool with an AI writing assistant is false; a company whose product IS an
  AI support agent is true."""


def format_sources(sources: list[dict]) -> str:
    parts = []
    for i, s in enumerate(sources, 1):
        parts.append(f"[S{i}] {s['kind']} | {s['url']}\n{s.get('title') or ''}\n{s['text']}")
    return "\n\n".join(parts)


def extract_profile(provider: BaseProvider, company: str, website: str, sources: list[dict]):
    user = f"Company: {company}\nWebsite: {website}\n\nSources:\n\n{format_sources(sources)}"
    return provider.structured(PROFILE_SYSTEM, user, "submit_profile", PROFILE_SCHEMA, max_tokens=2000)


# ---------------------------------------------------------------- 2. grounding

def _norm(text: str) -> str:
    text = text.lower().replace("’", "'").replace("“", '"').replace("”", '"').replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", re.sub(r"[^\w$%'.,:/-]+", " ", text)).strip()


def verify_facts(raw_facts: list[dict], sources: list[dict], min_score: float = 90.0) -> list[dict]:
    """Checks each quote against its cited source (falls back to all sources). Returns facts with verification."""
    normed = [_norm(s["text"]) for s in sources]
    out = []
    for n, f in enumerate(raw_facts, 1):
        quote = _norm(f.get("quote", ""))
        m = re.search(r"\d+", str(f.get("source", "")))
        idx = int(m.group()) if m else 0
        best, best_idx = 0.0, None
        if len(quote) >= 12:
            order = ([idx - 1] if 1 <= idx <= len(sources) else []) + [i for i in range(len(sources)) if i != idx - 1]
            for i in order:
                score = 100.0 if quote in normed[i] else fuzz.partial_ratio(quote, normed[i])
                if score > best:
                    best, best_idx = score, i
                if best >= 100:
                    break
        out.append({
            "fact_id": f"F{n}", "claim": f.get("claim", "").strip(), "quote": f.get("quote", "").strip(),
            "source_idx": (best_idx + 1) if best_idx is not None else (idx or None),
            "source_url": sources[best_idx]["url"] if best_idx is not None else None,
            "verified": best >= min_score, "match_score": round(best, 1),
        })
    return out


# ---------------------------------------------------------------- 3. fit scoring

SCORE_SCHEMA = {
    "type": "object",
    "properties": {"criteria": {"type": "array", "items": {"type": "object", "properties": {
        "id": {"type": "string"},
        "answer": {"type": "string", "enum": ["yes", "partial", "no", "unknown"]},
        "fact_ids": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    }, "required": ["id", "answer", "fact_ids", "reason"]}}},
    "required": ["criteria"],
}

SCORE_SYSTEM = """You assess how well a company fits an ideal-customer profile.
Answer every criterion using ONLY the verified facts given. Cite the fact ids that support each answer.
If the facts do not show it, answer 'unknown'. Do not use outside knowledge."""

POINTS = {"yes": 1.0, "partial": 0.5, "no": 0.0, "unknown": 0.0}


LARGE = {"employees": 1000, "annual_revenue_usd": 500_000_000, "valuation_usd": 1_000_000_000, "locations": 100}


def _num(v) -> float | None:
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def classify_size(profile: dict) -> tuple[str, str]:
    """Size decided in code from the extracted numbers. Returns (size, reason)."""
    emp, rev = _num(profile.get("employees")), _num(profile.get("annual_revenue_usd"))
    val, loc = _num(profile.get("valuation_usd")), _num(profile.get("locations"))
    if profile.get("publicly_listed") is True:
        return "large", "publicly listed"
    for key, limit in LARGE.items():
        v = {"employees": emp, "annual_revenue_usd": rev, "valuation_usd": val, "locations": loc}[key]
        if v is not None and v >= limit:
            label = {"employees": f"{v:,.0f} employees", "annual_revenue_usd": f"${v / 1e6:,.0f}M revenue",
                     "valuation_usd": f"${v / 1e9:,.1f}B valuation", "locations": f"{v:,.0f} locations"}[key]
            return "large", label
    if (emp is not None and emp >= 50) or (rev is not None and rev >= 10_000_000):
        return "mid", f"{emp:,.0f} employees" if emp is not None and emp >= 50 else f"${rev / 1e6:,.0f}M revenue"
    if emp is not None:
        return "small", f"{emp:,.0f} employees"
    return "unknown", "size not stated"


def score_fit(provider: BaseProvider, profile: dict, facts: list[dict], segment_cfg: dict,
              large_company_max: float | None = None):
    verified = [f for f in facts if f["verified"]]
    fact_text = "\n".join(f"{f['fact_id']}: {f['claim']}" for f in verified) or "(no verified facts)"
    crit_text = "\n".join(f"- {c['id']}: {c['question']}" for c in segment_cfg["criteria"])
    user = (f"Company: {profile.get('company_name')} ({profile.get('one_liner')})\n"
            f"Segment: {segment_cfg['label']}\n\nVerified facts:\n{fact_text}\n\nCriteria:\n{crit_text}")
    res = provider.structured(SCORE_SYSTEM, user, "submit_assessment", SCORE_SCHEMA, max_tokens=1200)
    return res, compute_score(res.data.get("criteria", []), segment_cfg, verified,
                              profile.get("size_signal"), large_company_max,
                              bool(profile.get("sells_ai_products")), profile.get("size_reason"))


def compute_score(judgements: list[dict], segment_cfg: dict, verified: list[dict],
                  size_signal: str | None = None, large_company_max: float | None = None,
                  sells_ai: bool = False, size_reason: str | None = None) -> dict:
    """Deterministic 0-10 score. A positive answer must cite at least one verified fact.
    Capped when the company is large (in-house AI teams) or already sells AI agents/automation itself."""
    valid_ids = {f["fact_id"] for f in verified}
    by_id = {j.get("id"): j for j in judgements}
    rows, total_w, got = [], 0.0, 0.0
    for c in segment_cfg["criteria"]:
        j = by_id.get(c["id"], {"answer": "unknown", "fact_ids": [], "reason": "not assessed"})
        answer = j.get("answer", "unknown")
        cited = [x for x in j.get("fact_ids", []) if x in valid_ids]
        downgraded = answer in ("yes", "partial") and not cited
        if downgraded:
            answer = "unknown"
        pts = POINTS.get(answer, 0.0) * c["weight"]
        total_w += c["weight"]
        got += pts
        rows.append({"id": c["id"], "question": c["question"], "weight": c["weight"], "answer": answer,
                     "fact_ids": cited, "reason": j.get("reason", ""), "points": pts, "downgraded": downgraded})
    score = round(10 * got / total_w, 1) if total_w else 0.0
    out = {"score": score, "criteria": rows}
    reasons = []
    if size_signal == "large":
        reasons.append(f"large company ({size_reason or 'per sources'}), which usually has its own AI teams")
    if sells_ai:
        reasons.append("its core product is AI agents or AI automation")
    if reasons and large_company_max is not None and score > large_company_max:
        out.update(score=float(large_company_max), uncapped_score=score, capped=True,
                   note=f"Capped at {large_company_max:g}/10: " + "; ".join(reasons) + ".")
    return out


# ---------------------------------------------------------------- 4. drafting + checks

DRAFT_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Plain, specific subject line, max 60 characters"},
        "body": {"type": "string", "description": "Email body only: greeting to the team, 3 short paragraphs, the call to action. No signature, no opt-out line."},
        "facts_used": {"type": "array", "items": {"type": "string"}, "description": "Fact ids referenced in the body"},
    },
    "required": ["subject", "body", "facts_used"],
}

DRAFT_SYSTEM = """You write short, honest B2B cold emails.
Rules:
- Open with ONE specific, verified fact about the company as the hook. Use at most one more fact after it.
  List every fact you use in facts_used (max 2). Never invent details.
- Pick ONE angle for the offer, and take it from the "Why they fit" reasons: the angle must follow from the
  evidence. Do not assume problems the facts don't suggest; phrase the need as a question
  (e.g. "Does your team spend much time on ...?").
- Name only ONE of the sender's capabilities, the one that matches the angle. Never list several services.
- Mention at most one proof point, and only if it relates to that capability.
- 60 to 120 words. Plain text, no bullet points, no emojis, no hype, no fake familiarity.
- Greet the team generically (e.g. "Hi {company} team,"); never invent a person's name.
- End with the call to action. Do NOT add a signature or opt-out line; they are added automatically."""

BANNED = ["i hope this email finds you well", "hope you're doing well", "synergy", "revolutionize", "game-changer",
          "game changer", "guarantee", "100%", "act now", "just checking in", "touch base", "circle back",
          "cutting-edge", "best-in-class", "i came across your profile", "dear sir"]


def check_draft(draft: dict, facts: list[dict], company: str) -> list[dict]:
    body, subject = draft.get("body", "") or "", draft.get("subject", "") or ""
    words = len(re.findall(r"\b\w[\w'-]*\b", body))
    verified_ids = {f["fact_id"] for f in facts if f["verified"]}
    used = draft.get("facts_used", []) or []
    low = (subject + " " + body).lower()
    # A phrase is only "hype" if the sender wrote it. Wording taken from the company's own verified facts
    # (e.g. "100% wool", "30-day guarantee") is allowed.
    fact_text = " ".join(f"{f.get('claim', '')} {f.get('quote', '')}" for f in facts if f["verified"]).lower()
    banned_hits = [b for b in BANNED if b in low and b not in fact_text]
    checks = [
        {"name": "Uses a verified fact", "passed": bool(used) and all(u in verified_ids for u in used),
         "detail": f"facts_used={used}"},
        {"name": "At most 2 facts", "passed": len(used) <= 2, "detail": f"{len(used)} facts used"},
        {"name": "Length 60-130 words", "passed": 60 <= words <= 130, "detail": f"{words} words"},
        {"name": "Subject under 60 characters", "passed": 0 < len(subject) <= 60, "detail": f"{len(subject)} chars"},
        {"name": "No banned phrases", "passed": not banned_hits, "detail": ", ".join(banned_hits)},
        {"name": "No placeholders", "passed": not re.search(r"\[[^\]]*\]|\{\{|\}\}|<[^>]+>", body + subject),
         "detail": ""},
        {"name": "Mentions the company", "passed": company.split()[0].lower() in low, "detail": ""},
        {"name": "No bullet lists", "passed": not re.search(r"^\s*([-*•]|\d+\.)\s", body, re.M), "detail": ""},
    ]
    return checks


def draft_email(provider: BaseProvider, profile: dict, facts: list[dict], score: dict, sender: dict,
                feedback: str | None = None):
    verified = [f for f in facts if f["verified"]]
    reasons = "; ".join(f"{c['id']}: {c['reason']}" for c in score["criteria"] if c["answer"] in ("yes", "partial"))
    user = (
        f"Sender: {sender['name']}, {sender['company']}. Offer: {sender['offer']}\n"
        f"Capabilities (mention only the ONE that fits the evidence): {' | '.join(sender.get('capabilities', []))}\n"
        f"Proof points: {' | '.join(sender['proof_points'])}\nCall to action: {sender['call_to_action']}\n\n"
        f"Company: {profile.get('company_name')}: {profile.get('one_liner')}\n"
        f"Why they fit: {reasons or 'general fit'}\n\nVerified facts:\n"
        + "\n".join(f"{f['fact_id']}: {f['claim']}" for f in verified)
    )
    if feedback:
        user += f"\n\nYour previous draft failed these checks, fix them: {feedback}"
    return provider.structured(DRAFT_SYSTEM, user, "submit_email", DRAFT_SCHEMA, max_tokens=800)


def finalize_body(body: str, sender: dict) -> str:
    return f"{body.strip()}\n\n{sender['signature']}\n\n{sender['opt_out']}"