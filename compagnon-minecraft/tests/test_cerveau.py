"""Teste le cerveau avec le vrai SDK groq, branché sur un faux serveur HTTP (aucun appel réseau)."""

import asyncio
import json
import unittest

import httpx

from compagnon_ia.budget import Budget
from compagnon_ia.cerveau import Cerveau, LimiteGroq, construire_systeme, duree_en_secondes
from compagnon_ia.config import Config


def morceau_sse(contenu=None, fin=False, usage=None):
    donnees = {"id": "c1", "object": "chat.completion.chunk", "created": 1, "model": "qwen/qwen3.8-27b",
               "choices": [{"index": 0, "delta": {} if contenu is None else {"content": contenu},
                            "finish_reason": "stop" if fin else None}]}
    if usage:
        donnees["x_groq"] = {"id": "req_1", "usage": usage}
    return f"data: {json.dumps(donnees)}\n\n"


class FauxGroq:
    def __init__(self):
        self.requetes = []
        self.reponses_429 = 0

    def __call__(self, requete: httpx.Request) -> httpx.Response:
        self.requetes.append(requete)
        chemin = requete.url.path
        if chemin.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": [
                {"id": "whisper-large-v3-turbo", "object": "model", "created": 0, "owned_by": "OpenAI"},
                {"id": "qwen/qwen3.8-27b", "object": "model", "created": 0, "owned_by": "Alibaba"}]})
        if chemin.endswith("/audio/transcriptions"):
            return httpx.Response(200, json={"text": " Tu as vu ce creeper ? "})
        if chemin.endswith("/chat/completions"):
            if self.reponses_429:
                self.reponses_429 -= 1
                return httpx.Response(429, headers={"retry-after": "0.01"},
                                      json={"error": {"message": "Rate limit reached. Please try again in 10ms."}})
            corps = "".join([morceau_sse("Oui, "), morceau_sse("il était juste derrière toi. "),
                             morceau_sse("Recule !"),
                             morceau_sse(fin=True, usage={"prompt_tokens": 1200, "completion_tokens": 20,
                                                          "total_tokens": 1220}),
                             "data: [DONE]\n\n"])
            return httpx.Response(200, content=corps.encode(), headers={
                "content-type": "text/event-stream", "x-ratelimit-remaining-requests": "987"})
        return httpx.Response(404, json={"error": {"message": "inconnu"}})


def creer_cerveau(faux: FauxGroq, **reglages) -> Cerveau:
    from groq import AsyncGroq

    cfg = Config(cle_api="test", **reglages)
    client = AsyncGroq(api_key="test", max_retries=0,
                       http_client=httpx.AsyncClient(transport=httpx.MockTransport(faux)))
    return Cerveau(cfg, construire_systeme(cfg, "Tu es un vieux routier.", "Chapitre 1 : la fuite."),
                   Budget(200_000, 40_000), client=client)


async def lire_tout(generateur):
    return [m async for m in generateur]


class TestCerveau(unittest.TestCase):
    def test_reponse_en_streaming_avec_image(self):
        faux = FauxGroq()
        cerveau = creer_cerveau(faux, pseudo="Arthur")
        cerveau.memoriser("[Voix] Salut", "Salut, Seigneur.")
        morceaux = asyncio.run(lire_tout(cerveau.repondre("[Voix] Tu vois ?", "data:image/jpeg;base64,AAAA")))
        self.assertEqual("".join(morceaux), "Oui, il était juste derrière toi. Recule !")
        self.assertEqual(cerveau.derniers_jetons, 1220)
        self.assertEqual(cerveau.budget.jetons_jour, 1220)
        self.assertEqual(cerveau.budget.requetes_restantes, 987)

        corps = json.loads(faux.requetes[-1].content)
        self.assertEqual(corps["model"], "qwen/qwen3.8-27b")
        self.assertEqual(corps["reasoning_effort"], "none")
        self.assertNotIn("reasoning_format", corps)
        self.assertTrue(corps["stream"])
        messages = corps["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("Chapitre 1", messages[0]["content"])
        self.assertIn("Arthur", messages[0]["content"])
        self.assertEqual(messages[1], {"role": "user", "content": "[Voix] Salut"})  # historique en texte seul
        self.assertEqual(messages[-1]["content"][1]["image_url"]["url"], "data:image/jpeg;base64,AAAA")

    def test_transcription(self):
        faux = FauxGroq()
        cerveau = creer_cerveau(faux, vocabulaire="creeper")
        texte = asyncio.run(cerveau.transcrire(b"fLaC..."))
        self.assertEqual(texte, "Tu as vu ce creeper ?")
        requete = faux.requetes[-1]
        self.assertIn(b"whisper-large-v3-turbo", requete.content)
        self.assertIn(b'name="language"', requete.content)

    def test_429_reessaye_puis_reussit(self):
        faux = FauxGroq()
        faux.reponses_429 = 1
        cerveau = creer_cerveau(faux)
        morceaux = asyncio.run(lire_tout(cerveau.repondre("[Voix] Alors ?", None)))
        self.assertTrue(morceaux)
        self.assertEqual(len([r for r in faux.requetes if r.url.path.endswith("/chat/completions")]), 2)

    def test_429_spontane_abandonne_tout_de_suite(self):
        faux = FauxGroq()
        faux.reponses_429 = 1
        cerveau = creer_cerveau(faux)
        with self.assertRaises(LimiteGroq) as ctx:
            asyncio.run(lire_tout(cerveau.repondre("[Coup d'œil]", None, spontane=True)))
        self.assertAlmostEqual(ctx.exception.attente, 0.01)

    def test_liste_modeles(self):
        cerveau = creer_cerveau(FauxGroq())
        self.assertIn("qwen/qwen3.8-27b", asyncio.run(cerveau.lister_modeles()))

    def test_memoire_limitee(self):
        cerveau = creer_cerveau(FauxGroq(), echanges=2)
        for i in range(5):
            cerveau.memoriser(f"q{i}", f"r{i}")
        self.assertEqual([m["content"] for m in cerveau.historique], ["q3", "r3", "q4", "r4"])

    def test_durees(self):
        self.assertEqual(duree_en_secondes("2m59.5s"), 179.5)
        self.assertEqual(duree_en_secondes("120ms"), 0.12)
        self.assertEqual(duree_en_secondes("7"), 7.0)
        self.assertIsNone(duree_en_secondes(""))


if __name__ == "__main__":
    unittest.main()
