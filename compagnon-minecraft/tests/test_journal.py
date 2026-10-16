import asyncio
import tempfile
import unittest
from pathlib import Path

from compagnon_ia.boucle import Compagnon
from compagnon_ia.journal_jeu import AnalyseurLog, EvenementJeu, SurveillantLog, ligne_simulee
from tests.faux import FausseCapture, FausseSynthese, FauxCerveau, FauxLecteur, FauxMicro, config_test

A = AnalyseurLog("Arthur", "@compagnon")


def genre(ligne):
    evenement = A.analyser(ligne)
    return evenement.genre if evenement else None


class TestAnalyseur(unittest.TestCase):
    def test_morts_francais_et_anglais(self):
        for ligne in (
            "[21:04:11] [Server thread/INFO]: Arthur a été tué par Zombie",
            "[21:04:11] [Server thread/INFO]: Arthur a explosé à cause de Creeper",
            "[21:04:11] [Server thread/INFO]: Arthur a heurté le sol trop violemment",
            "[21:04:11] [Server thread/INFO]: Arthur s'est noyé",
            "[21:04:11] [Render thread/INFO]: [System] [CHAT] Arthur a essayé de nager dans la lave",
            "[21:04:11] [Server thread/INFO]: Arthur was slain by Zombie",
            "[21:04:11] [Server thread/INFO]: Arthur was blown up by Creeper",
            "[21:04:11] [Server thread/INFO]: Arthur fell from a high place",
            "[21:04:11] [Server thread/INFO]: Arthur drowned",
            "[21:04:11] [Server thread/INFO]: Arthur hit the ground too hard",
        ):
            self.assertEqual(genre(ligne), "mort", ligne)

    def test_formats_forge_et_fabric(self):
        self.assertEqual(genre("[16Oct2026 21:04:11.123] [Server thread/INFO] "
                               "[net.minecraft.server.MinecraftServer/]: Arthur a été tué par Squelette"), "mort")
        self.assertEqual(genre("[21:04:11] [Server thread/INFO] (Minecraft) Arthur drowned"), "mort")

    def test_progres(self):
        e = A.analyser("[21:05:00] [Server thread/INFO]: Arthur a obtenu le progrès [L'âge de pierre]")
        self.assertEqual((e.genre, e.detail), ("progres", "L'âge de pierre"))
        e = A.analyser("[21:05:00] [Server thread/INFO]: Arthur has made the advancement [Diamonds!]")
        self.assertEqual((e.genre, e.detail), ("progres", "Diamonds!"))
        self.assertEqual(genre("[21:05:00] [Server thread/INFO]: Arthur has completed the challenge "
                               "[Monsters Hunted]"), "progres")

    def test_chat_compagnon(self):
        e = A.analyser("[21:06:00] [Server thread/INFO]: <Arthur> @compagnon tu en penses quoi ?")
        self.assertEqual((e.genre, e.detail), ("chat", "tu en penses quoi ?"))
        e = A.analyser("[21:06:00] [Render thread/INFO]: [CHAT] [Not Secure] <Arthur> @Compagnon, salut")
        self.assertEqual((e.genre, e.detail), ("chat", "salut"))
        self.assertIsNone(A.analyser("[21:06:00] [Server thread/INFO]: <Arthur> salut tout le monde"))
        self.assertIsNone(A.analyser("[21:06:00] [Server thread/INFO]: <Merlin> @compagnon coucou"))

    def test_lignes_ignorees(self):
        for ligne in (
            "[21:00:00] [Server thread/INFO]: Arthur a rejoint la partie",
            "[21:00:00] [Server thread/INFO]: Arthur joined the game",
            "[21:00:00] [Server thread/INFO]: Arthur[local:E:1234] logged in with entity id 42",
            "[21:00:00] [Server thread/INFO]: Merlin a été tué par Zombie",
            "[21:00:00] [Server thread/INFO]: Saving chunks for level 'ServerLevel[Royaume]'/minecraft:overworld",
            "[21:00:00] [Render thread/WARN]: Arthur was slain by Zombie",
            "pas une ligne de log",
        ):
            self.assertIsNone(genre(ligne), ligne)

    def test_lignes_simulees_reconnues(self):
        for g in ("mort", "progres", "chat"):
            self.assertEqual(genre(ligne_simulee(g, "Arthur")), g)


class TestSurveillant(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.chemin = Path(self.dossier.name) / "latest.log"
        self.recus: list[EvenementJeu] = []
        self.s = SurveillantLog(self.chemin, A, self.recus.append)

    def tearDown(self):
        self.dossier.cleanup()

    def ajouter(self, texte):
        with open(self.chemin, "a", encoding="utf-8", newline="") as f:
            f.write(texte)

    def lire(self):
        return self.s.traiter(self.s.lire_nouveautes())

    def test_ancien_contenu_ignore_puis_nouvelles_lignes(self):
        self.ajouter("[20:00:00] [Server thread/INFO]: Arthur a été tué par Zombie\n")
        self.assertEqual(self.lire(), [])  # démarrage : on ne rejoue pas le passé
        self.ajouter("[20:01:00] [Server thread/INFO]: Arthur s'est noyé\r\n")
        self.assertEqual([e.texte for e in self.lire()], ["Arthur s'est noyé"])

    def test_ligne_coupee_en_deux(self):
        self.ajouter("")
        self.lire()
        self.ajouter("[20:01:00] [Server thread/INFO]: Arthur a ")
        self.assertEqual(self.lire(), [])
        self.ajouter("explosé\n")
        self.assertEqual([e.genre for e in self.lire()], ["mort"])

    def test_doublon_serveur_et_client(self):
        self.ajouter("")
        self.lire()
        self.ajouter("[20:01:00] [Server thread/INFO]: Arthur drowned\n"
                     "[20:01:00] [Render thread/INFO]: [System] [CHAT] Arthur drowned\n")
        self.assertEqual(len(self.lire()), 1)

    def test_fichier_recree_au_lancement_du_jeu(self):
        self.ajouter("[20:00:00] [main/INFO]: " + "x" * 500 + "\n")
        self.lire()
        self.chemin.unlink()
        self.ajouter("[20:30:00] [Server thread/INFO]: Arthur a été tué par Enderman\n")
        self.assertEqual([e.genre for e in self.lire()], ["mort"])

    def test_fichier_absent_au_demarrage(self):
        self.assertEqual(self.lire(), [])
        self.ajouter("[20:30:00] [Server thread/INFO]: <Arthur> @compagnon coucou\n")
        self.assertEqual([e.detail for e in self.lire()], ["coucou"])


class TestEvenementsDansLaBoucle(unittest.TestCase):
    def test_mort_declenche_une_reponse_avec_capture(self):
        async def scenario():
            c = Compagnon(config_test(), cerveau=FauxCerveau(["Encore ? Ce zombie t'a bien eu."]),
                          synthese=FausseSynthese(), lecteur=FauxLecteur(), micro=FauxMicro(),
                          capture=FausseCapture())
            c.fichier_capture = None
            c._sur_evenement(EvenementJeu("mort", "Arthur a été tué par Zombie"))
            await asyncio.gather(*c._taches)
            await c._tour
            return c

        c = asyncio.run(scenario())
        self.assertIn("[Événement] Le seigneur vient de mourir", c.cerveau.entrees[0])
        self.assertIsNotNone(c.cerveau.images[0])
        self.assertEqual(c.synthese.textes, ["Encore ?", "Ce zombie t'a bien eu."])

    def test_chat_passe_en_tour_chat(self):
        async def scenario():
            c = Compagnon(config_test(), cerveau=FauxCerveau(), synthese=FausseSynthese(),
                          lecteur=FauxLecteur(), micro=FauxMicro(), capture=FausseCapture())
            c.fichier_capture = None
            c._sur_evenement(EvenementJeu("chat", "<Arthur> @compagnon salut", "salut"))
            await asyncio.gather(*c._taches)
            await c._tour
            return c

        self.assertEqual(asyncio.run(scenario()).cerveau.entrees, ["[Chat] salut"])


if __name__ == "__main__":
    unittest.main()
