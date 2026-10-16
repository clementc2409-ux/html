import asyncio
import time
import unittest

from PIL import Image

from compagnon_ia.boucle import Compagnon, Demande
from compagnon_ia.budget import Budget
from compagnon_ia.capture import difference, empreinte
from compagnon_ia.cerveau import LimiteGroq
from tests.faux import FausseCapture, FausseSynthese, FauxCerveau, FauxLecteur, FauxMicro, config_test

VERT, GRIS = (40, 120, 40), (90, 90, 90)


def creer(reponses=None, couleurs=(VERT,), **reglages):
    reglages.setdefault("fenetre_minecraft", "")
    c = Compagnon(config_test(**reglages), cerveau=FauxCerveau(reponses), synthese=FausseSynthese(),
                  lecteur=FauxLecteur(), micro=FauxMicro(), capture=FausseCapture(couleurs))
    c.budget = Budget(0, 1_000_000)  # budget illimité pour ces tests
    return c


async def coup_d_oeil(c):
    await c._coup_d_oeil()
    if c._tour is not None:
        await c._tour


class TestCommentairesSpontanes(unittest.TestCase):
    def test_silence_ne_dit_rien(self):
        c = creer(["SILENCE"])
        asyncio.run(coup_d_oeil(c))
        self.assertEqual(len(c.cerveau.entrees), 1)
        self.assertIn("[Coup d'œil]", c.cerveau.entrees[0])
        self.assertEqual(c.synthese.textes, [])
        self.assertEqual(c.cerveau.historique, [])
        self.assertEqual(c._dernier_spontane, float("-inf"))  # pas de cooldown : il n'a rien dit

    def test_commentaire_puis_cooldown(self):
        async def scenario():
            c = creer(["Joli point de vue pour une tour de guet.", "Encore un ?"], couleurs=(VERT, GRIS))
            await coup_d_oeil(c)
            c._fin_parole = float("-inf")
            await coup_d_oeil(c)  # écran changé, mais cooldown de 45 s
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.synthese.textes, ["Joli point de vue pour une tour de guet."])
        self.assertEqual(len(c.cerveau.entrees), 1)
        self.assertIn("cooldown", c._occupe())

    def test_ecran_inchange_pas_envoye(self):
        c = creer(["SILENCE", "SILENCE"])
        asyncio.run(coup_d_oeil(c))
        asyncio.run(coup_d_oeil(c))  # même image : rien n'est envoyé
        self.assertEqual(len(c.cerveau.entrees), 1)

    def test_ecran_change_envoye(self):
        c = creer(["SILENCE", "SILENCE"], couleurs=(VERT, GRIS))
        asyncio.run(coup_d_oeil(c))
        asyncio.run(coup_d_oeil(c))
        self.assertEqual(len(c.cerveau.entrees), 2)

    def test_ne_coupe_jamais_une_reponse(self):
        async def scenario():
            c = creer(["Une réponse assez longue pour durer un moment, vraiment."])
            c.cerveau.delai = 0.02
            await c.soumettre(Demande("voix", "Raconte"))
            accepte = await c.soumettre(Demande("spontane", image=Image.new("RGB", (64, 36))))
            await c._tour
            return c, accepte

        c, accepte = asyncio.run(scenario())
        self.assertFalse(accepte)
        self.assertEqual(c.cerveau.entrees, ["[Voix] Raconte"])

    def test_ta_voix_coupe_un_commentaire_spontane(self):
        async def scenario():
            c = creer(["Tiens, regarde ce coucher de soleil sur la vallée, magnifique.", "Oui ?"])
            c.cerveau.delai = 0.02
            await c.soumettre(Demande("spontane", image=Image.new("RGB", (64, 36))))
            await asyncio.sleep(0.05)
            spontane = c._tour
            await c.soumettre(Demande("voix", "Attends"))
            await c._tour
            return c, spontane

        c, spontane = asyncio.run(scenario())
        self.assertTrue(spontane.cancelled())
        self.assertEqual(c.cerveau.entrees[-1], "[Voix] Attends")

    def test_limite_groq_abandonne_et_met_en_pause(self):
        class CerveauLimite(FauxCerveau):
            async def repondre(self, entree, image_url, spontane=False):
                raise LimiteGroq(30.0, "trop de requêtes")
                yield  # pragma: no cover

        c = creer()
        c.cerveau = CerveauLimite()
        asyncio.run(coup_d_oeil(c))
        self.assertEqual(c.synthese.textes, [])
        autorise, raison = c.budget.autorise_spontane()
        self.assertFalse(autorise)
        self.assertIn("pause", raison)


class TestBudget(unittest.TestCase):
    def test_seau_horaire(self):
        b = Budget(0, 36_000)  # 10 jetons/s, réserve max 6 000
        self.assertTrue(b.autorise_spontane()[0])
        b.enregistrer(6_000, spontane=True)
        autorise, raison = b.autorise_spontane()
        self.assertFalse(autorise)
        self.assertIn("budget horaire", raison)
        b._maj -= 600  # 10 minutes plus tard
        self.assertTrue(b.autorise_spontane()[0])

    def test_quota_du_jour_garde_pour_les_questions(self):
        b = Budget(10_000, 1_000_000)
        b.enregistrer(8_500, spontane=False)
        autorise, raison = b.autorise_spontane()
        self.assertFalse(autorise)
        self.assertIn("quota", raison)

    def test_requetes_restantes(self):
        b = Budget(0, 1_000_000)
        b.noter_entetes({"x-ratelimit-remaining-requests": "12"})
        self.assertFalse(b.autorise_spontane()[0])

    def test_pause(self):
        b = Budget(0, 1_000_000)
        b.pause_spontanes(5)
        self.assertFalse(b.autorise_spontane()[0])
        b.pause_jusqua = time.monotonic() - 1
        self.assertTrue(b.autorise_spontane()[0])


class TestComparaison(unittest.TestCase):
    def test_difference(self):
        a = empreinte(Image.new("RGB", (1920, 1080), VERT))
        b = empreinte(Image.new("RGB", (1920, 1080), GRIS))
        self.assertEqual(difference(a, a), 0.0)
        self.assertGreater(difference(a, b), 0.04)


if __name__ == "__main__":
    unittest.main()
