"""Checker rules 3 and 5 (LLD §8) on the AI Services resource, keyless (Entra ID):
Azure AI Translator back-translates Spanish and Hindi captions to English so they are checked the
same way as English ones (IG-23), and Azure AI Content Safety screens every caption (IG-24).
"""

import asyncio
import os

import httpx

from insights import checker

ENDPOINT = os.environ.get("AZURE_AI_ENDPOINT",
                          "https://offball-ai-kr2610.cognitiveservices.azure.com/").rstrip("/")
SCOPE = "https://cognitiveservices.azure.com/.default"
MAX_SEVERITY = 1  # Content Safety severities run 0, 2, 4, 6; anything above 0 is off-air for us


class Safety:
    def __init__(self, credential):
        self.credential = credential
        self.http = httpx.AsyncClient(timeout=5.0)

    async def close(self) -> None:
        await self.http.aclose()

    async def _headers(self) -> dict:
        token = await self.credential.get_token(SCOPE)
        return {"Authorization": f"Bearer {token.token}", "Content-Type": "application/json"}

    async def back_translate(self, captions: dict[str, str]) -> dict[str, str]:
        """{key: English} for every non-English caption, in one request."""
        keys = [k for k in captions if not k.endswith(".en")]
        if not keys:
            return {}
        r = await self.http.post(f"{ENDPOINT}/translator/text/v3.0/translate?api-version=3.0&to=en",
                                 headers=await self._headers(),
                                 json=[{"text": captions[k]} for k in keys])
        r.raise_for_status()
        return {k: item["translations"][0]["text"] for k, item in zip(keys, r.json())}

    async def harmful(self, text: str) -> list[str]:
        r = await self.http.post(f"{ENDPOINT}/contentsafety/text:analyze?api-version=2024-09-01",
                                 headers=await self._headers(), json={"text": text})
        r.raise_for_status()
        return [f"content safety: {c['category']} severity {c['severity']}"
                for c in r.json()["categoriesAnalysis"] if c["severity"] > MAX_SEVERITY]

    async def review(self, captions: dict[str, str], g: checker.Grounding) -> dict[str, list[str]]:
        """Reasons per caption key; a caption with no reasons passed."""
        english, *flags = await asyncio.gather(self.back_translate(captions),
                                               *(self.harmful(t) for t in captions.values()))
        reasons = dict(zip(captions, flags))
        for key, text in english.items():
            # Same rules as English; no word limit, a translation's length says nothing
            found = (checker.check_numbers(text, "en", g)
                     + checker.check_claims(text, g.facts, g.tool_results)
                     + checker.check_pairs(text))
            reasons[key] += [f"back-translation ({text!r}): {r}" for r in found]
        return reasons
