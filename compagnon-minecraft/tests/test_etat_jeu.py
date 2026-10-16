import json
import tempfile
import time
import unittest
from pathlib import Path

from PIL import Image

from compagnon_ia.etat_jeu import Alertes, CapteurEtat, ajouter_bande, dimension, heure_du_jour, resume


def etat(**modifs):
    e = {"horodatage": int(time.time() * 1000),
         "joueur": {"vie": 14.0, "vie_max": 20.0, "faim": 12, "armure": 8, "niveau": 12, "air": 300, "air_max": 300,
                    "en_feu": False, "dimension": "ResourceKey[minecraft:dimension / minecraft:overworld]",
                    "biome": "Forêt de bouleaux", "main": {"nom": "Épée en fer"}},
         "monde": {"heure": 4000, "pluie": True, "orage": False},
         "vise": {"type": "bloc", "nom": "Bûche de bouleau"},
         "menu": None, "pause": False,
         "monstres": [{"nom": "Zombie", "id": "minecraft:zombie", "distance": 12.3, "direction": "devant"}],
         "evenements": []}
    for cle, valeur in modifs.items():
        if cle in e["joueur"]:
            e["joueur"][cle] = valeur
        else:
            e[cle] = valeur
    return e


class TestResume(unittest.TestCase):
    def test_resume_exact(self):
        texte = resume(etat())
        for morceau in ("Vie 14/20", "Faim 12/20", "Armure 8", "Niveau 12", "Forêt de bouleaux", "la Surface",
                        "10 h, jour", "pluie", "En main : Épée en fer", "Vise : Bûche de bouleau",
                        "Zombie à 12 blocs devant"):
            self.assertIn(morceau, texte)

    def test_dimension_et_heure(self):
        self.assertEqual(dimension(etat(dimension="minecraft:the_nether")), "le Nether")
        self.assertEqual(heure_du_jour({"monde": {"heure": 18000}}), "0 h, nuit")
        self.assertEqual(heure_du_jour({"monde": {"heure": 12500}}), "18 h, coucher du soleil")

    def test_bande_sous_l_image(self):
        image = Image.new("RGB", (1280, 720), (90, 160, 60))
        avec = ajouter_bande(image, etat())
        self.assertEqual(avec.width, 1280)
        self.assertGreater(avec.height, 720)
        self.assertEqual(avec.getpixel((5, 719)), (90, 160, 60))  # l'image d'origine reste intacte


class TestCapteur(unittest.TestCase):
    def test_frais_ou_perime(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "etat.json"
            capteur = CapteurEtat(chemin)
            self.assertIsNone(capteur.lire())  # pas encore de fichier
            chemin.write_text(json.dumps(etat()), encoding="utf-8")
            self.assertIsNotNone(capteur.lire())
            self.assertTrue(capteur.frais)
            vieux = etat(horodatage=int((time.time() - 30) * 1000))
            chemin.write_text(json.dumps(vieux), encoding="utf-8")
            self.assertIsNone(capteur.lire())  # jeu fermé : données trop vieilles

    def test_menu_ou_pause(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "etat.json"
            chemin.write_text(json.dumps(etat(menu="PauseScreen")), encoding="utf-8")
            capteur = CapteurEtat(chemin)
            capteur.lire()
            self.assertTrue(capteur.menu_ou_pause)


class TestAlertes(unittest.TestCase):
    def test_creeper_dans_le_dos(self):
        a = Alertes()
        apres = etat(monstres=[{"nom": "Creeper", "id": "minecraft:creeper", "distance": 3.2, "direction": "derrière"}])
        alertes = a.detecter(etat(), apres)
        self.assertEqual(alertes, ["Creeper à 3 blocs derrière lui !"])
        self.assertEqual(a.detecter(apres, apres), [])  # pas de répétition immédiate

    def test_zombie_devant_pas_d_alerte(self):
        apres = etat(monstres=[{"nom": "Zombie", "id": "minecraft:zombie", "distance": 4, "direction": "devant"}])
        self.assertEqual(Alertes().detecter(etat(), apres), [])

    def test_vie_basse_gros_degats_faim_noyade_feu(self):
        a = Alertes()
        alertes = a.detecter(etat(vie=14.0), etat(vie=5.0, evenements=[{"type": "degats", "cause": "Squelette"}]))
        self.assertTrue(any("4.5 cœurs d'un coup (Squelette)" in x for x in alertes))
        self.assertTrue(any("plus que 2.5 cœurs" in x for x in alertes))
        self.assertTrue(any("faim" in x for x in a.detecter(etat(faim=8), etat(faim=6))))
        self.assertTrue(any("noyer" in x for x in a.detecter(etat(), etat(air=40))))
        self.assertTrue(any("en feu" in x for x in a.detecter(etat(), etat(en_feu=True))))

    def test_nether_et_coucher_du_soleil(self):
        a = Alertes()
        self.assertTrue(any("Nether" in x for x in a.detecter(etat(), etat(dimension="minecraft:the_nether"))))
        soir = etat(monde={"heure": 12100})
        self.assertTrue(any("soleil se couche" in x for x in Alertes().detecter(etat(monde={"heure": 11900}), soir)))

    def test_rien_pendant_un_menu(self):
        apres = etat(menu="InventoryScreen", vie=3.0)
        self.assertEqual(Alertes().detecter(etat(), apres), [])


class TestSimulation(unittest.TestCase):
    def test_scenarios_declenchent_les_alertes(self):
        from compagnon_ia.etat_jeu import SCENARIOS, etat_simule

        for scenario in SCENARIOS:
            self.assertIn("Vie 18/20", resume(etat_simule(scenario, 0)))
        a = Alertes()
        alertes = [x for t in range(0, 20) for x in a.detecter(etat_simule("creeper", t - 1), etat_simule("creeper", t))]
        self.assertEqual(len(alertes), 1)
        self.assertIn("Creeper", alertes[0])
        self.assertIn("derrière lui", alertes[0])
        a = Alertes()
        alertes = [x for t in range(0, 20) for x in a.detecter(etat_simule("blesse", t - 1), etat_simule("blesse", t))]
        self.assertTrue(any("cœurs d'un coup (Squelette)" in x for x in alertes))
        self.assertTrue(any("plus que 2.5 cœurs" in x for x in alertes))
        self.assertEqual(Alertes().detecter(etat_simule("capteur", 0), etat_simule("capteur", 10)), [])


if __name__ == "__main__":
    unittest.main()
