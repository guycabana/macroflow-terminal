"""
ai_brief.py
-----------
The AI narration layer for MacroFlow Terminal.

Principle (the spine of the whole project): the CODE computes the facts,
the AI only NARRATES them. The model is given pre-computed regime flags and
market levels with their data sources, and is forbidden from inventing
numbers, probabilities, or events that aren't in the facts.

This is deliberately the opposite of a stuffed "always output a trade with
an X% probability" prompt -- those numbers would be fabricated. Here the AI
explains what the verified facts mean and says so plainly when there's no
clean signal.
"""

SYSTEM_PROMPT = """You are a macro analyst writing a short brief for a markets operator.

You will be given PRE-COMPUTED facts (regime flags and market levels) with their
data sources. Your job is to narrate what these facts mean for risk assets.

Hard rules:
- Use ONLY the facts provided. Do not introduce any data, price level, or event
  that is not in the facts.
- Never invent probabilities, percentages, win-rates, or price targets. If you
  state a number, it must appear verbatim in the facts.
- If regimes are INACTIVE/NEUTRAL/UNKNOWN or signals conflict, say so plainly.
  "No clean signal right now" is a valid and useful conclusion.
- Write 4-6 tight bullets. Concrete, no hype, no disclaimers.
- End with one line beginning "Watch:" naming the single most important data
  point or threshold to watch next. This is a watch-item, NOT a trade recommendation.
"""


def build_facts(flags, market_lines=None) -> str:
    """Turn computed regime flags + market level strings into a fact block."""
    out = ["REGIMES (pre-computed -- do not alter or extend):"]
    for f in flags:
        src = ", ".join(f"{p.series_id}@{p.as_of}" for p in f.inputs) or "n/a"
        nums = "; ".join(f"{k}={v}" for k, v in f.computed.items()) or "no data"
        out.append(f"- {f.name}: {f.status} | {nums} | rule: {f.rule} | src: FRED[{src}]")
    if market_lines:
        out.append("")
        out.append("MARKET LEVELS (pre-computed):")
        out.extend(f"- {ln}" for ln in market_lines)
    return "\n".join(out)


def generate_brief(api_key, flags, market_lines=None,
                   model="claude-haiku-4-5", max_tokens=700) -> str:
    """Call the Claude API to narrate the facts. Import is lazy so this module
    loads even where the anthropic package isn't installed."""
    import anthropic

    facts = build_facts(flags, market_lines)
    client = anthropic.Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": facts}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
