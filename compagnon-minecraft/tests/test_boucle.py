import asyncio
import unittest

import numpy as np

from compagnon_ia.boucle import Compagnon, Demande
from compagnon_ia.voix import Lecteur
from tests.faux import FausseCapture, FausseSynthese, FauxCerveau, FauxLecteur, FauxMicro, config_test


def creer(cerveau=None, lecteur=None, **reglages):
    c = Compagnon(config_test(**reglages), cerveau=cerveau or FauxCerveau(), synthese=FausseSynthese(),
                  lecteur=lecteur or FauxLecteur(), micro=FauxMicro(), capture=FausseCapture())
    c.micro_actif = True  # comme si le micro s'était ouvert au démarrage
    return c


async def attendre_tour(c):
    while c._tour is None or not c._tour.done():
        await asyncio.sleep(0.005)


class TestPushToTalk(unittest.TestCase):
    def test_voix_transcrite_capture_et_reponse_phrase_par_phrase(self):
        async def scenario():
            c = creer(FauxCerveau(["Oui, je le vois. Recule doucement !"]))
            c._appui()
            self.assertTrue(c.micro.enregistre)
            c._relache()
            await c._tache_voix
            await attendre_tour(c)
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.cerveau.entrees, ["[Voix] Tu vois ce creeper ?"])
        self.assertTrue(c.cerveau.images[0].startswith("data:image/jpeg;base64,"))
        self.assertEqual(c.synthese.textes, ["Oui, je le vois.", "Recule doucement !"])
        self.assertEqual(c.cerveau.historique,
                         [("[Voix] Tu vois ce creeper ?", "Oui, je le vois. Recule doucement !")])

    def test_appui_interrompt_la_parole(self):
        async def scenario():
            c = creer(FauxCerveau(["Une très longue histoire qui ne finit jamais vraiment, " * 3], delai=0.02),
                      FauxLecteur(duree=1.0))
            await c.soumettre(Demande("voix", "Raconte"))
            while not c.cerveau.entrees:  # capture + JPEG peuvent être lents au premier lancement
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.08)  # il a commencé à répondre
            c._appui()                 # on appuie : il doit se taire tout de suite
            await asyncio.sleep(0.02)
            return c

        c = asyncio.run(scenario())
        self.assertGreaterEqual(c.lecteur.interruptions, 1)
        self.assertTrue(c._tour.cancelled())
        self.assertTrue(c.cerveau.historique[0][1].endswith("[…interrompu]"))

    def test_demande_annulee_pendant_l_attente_ne_relance_rien(self):
        # Double appui rapide : la 1re phrase, en train de couper l'ancienne réponse, est annulée à son tour.
        async def scenario():
            c = creer(FauxCerveau(["Une longue réponse qui prend son temps pour venir, vraiment."], delai=0.02))
            await c.soumettre(Demande("voix", "A"))
            while not c.cerveau.entrees:  # la réponse à A a commencé
                await asyncio.sleep(0.01)
            premier = c._tour
            demande_b = asyncio.create_task(c.soumettre(Demande("voix", "B")))
            await asyncio.sleep(0)
            demande_b.cancel()
            await asyncio.wait({demande_b})
            await asyncio.sleep(0.05)
            return c, premier, demande_b

        c, premier, demande_b = asyncio.run(scenario())
        self.assertTrue(demande_b.cancelled())
        self.assertIs(c._tour, premier)
        self.assertEqual(c.cerveau.entrees, ["[Voix] A"])

    def test_appui_trop_court_ignore(self):
        async def scenario():
            c = creer()
            c.micro.arreter = lambda: np.zeros(1000, dtype=np.int16)
            c._appui()
            c._relache()
            await c._tache_voix
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.cerveau.entrees, [])


class TestMicroIndisponible(unittest.TestCase):
    def test_appui_sans_micro_previent_sans_planter(self):
        async def scenario():
            c = creer()
            c.micro_actif, c.erreur_micro = False, "accès refusé"
            with self.assertLogs("compagnon", level="WARNING") as journaux:
                c._appui()
            c._relache()
            return c, journaux

        c, journaux = asyncio.run(scenario())
        self.assertFalse(c.micro.enregistre)
        self.assertIn("accès refusé", journaux.output[0])


class TestLecteur(unittest.TestCase):
    def test_lecture_puis_interruption(self):
        lecteur = Lecteur()
        lecteur._flux = object()  # comme si la sortie audio était ouverte
        lecteur.jouer(np.full(100, 0.5, dtype=np.float32))
        lecteur.jouer(np.full(100, 0.25, dtype=np.float32))
        sortie = np.zeros((150, 1), dtype=np.float32)
        lecteur._rappel(sortie, 150, None, None)
        self.assertTrue(np.all(sortie[:100, 0] == 0.5) and np.all(sortie[100:, 0] == 0.25))
        self.assertTrue(lecteur.parle)
        lecteur.interrompre()
        self.assertFalse(lecteur.parle)
        lecteur._rappel(sortie, 150, None, None)
        self.assertTrue(np.all(sortie == 0))


if __name__ == "__main__":
    unittest.main()
