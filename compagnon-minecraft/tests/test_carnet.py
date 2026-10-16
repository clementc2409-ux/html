"""Carnet du royaume, outils Gemini (function calling) et recherche dans le wiki."""

import asyncio
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from google.genai import types

from compagnon_ia import wiki
from compagnon_ia.carnet import Carnet, prompt_resume
from compagnon_ia.etat_jeu import CapteurEtat
from compagnon_ia.live import construire_config, construire_consignes
from compagnon_ia.outils import Outils, declarations
from compagnon_ia.souvenirs import Souvenirs
from tests.faux import config_test
from tests.test_live import FausseSession, creer


class TestCarnet(unittest.TestCase):
    def test_projets(self):
        c = Carnet(None)
        self.assertIn("noté", c.noter_projet("Port du Sud", "au bord de la baie")["resultat"])
        self.assertIn("mis à jour", c.noter_projet("port du sud", "avec un phare")["resultat"])
        self.assertEqual(len(c.donnees["projets"]), 1)
        self.assertEqual(c.donnees["projets"][0]["details"], "avec un phare")
        self.assertIn("terminé", c.terminer_projet("le port")["resultat"])  # nom approximatif
        self.assertIn("erreur", c.terminer_projet("Barrage"))
        self.assertEqual(c.consulter()["projets_termines"], ["Port du Sud"])

    def test_quetes(self):
        c = Carnet(None)
        self.assertIn("erreur", c.ajouter_quete("Sans objectif", ""))
        c.ajouter_quete("La salle du trône", "rapporter 20 blocs de quartz", "le titre de Bâtisseur")
        self.assertIn("erreur", c.ajouter_quete("La salle du trone", "autre chose"))  # déjà en cours
        self.assertEqual([q["titre"] for q in c.quetes_en_cours()], ["La salle du trône"])
        fin = c.terminer_quete("salle du trone")
        self.assertIn("accomplie", fin["resultat"])
        self.assertIn("Bâtisseur", fin["resultat"])
        self.assertEqual(c.quetes_en_cours(), [])

    def test_lieux_avec_et_sans_coordonnees(self):
        c = Carnet(None)
        r = c.noter_lieu("Portail du Nether", "à côté de la mine",
                         {"x": 120.4, "y": 64.0, "z": -33.6,
                          "dimension": "ResourceKey[minecraft:dimension / minecraft:the_nether]"})
        self.assertIn("X 120 Y 64 Z -34 (Nether)", r["resultat"])
        self.assertIn("sans coordonnées", c.noter_lieu("Village", "")["resultat"])
        c.noter_lieu("Village", "", {"x": 5, "y": 70, "z": 9, "dimension": "minecraft:overworld"})
        self.assertEqual(len(c.donnees["lieux"]), 2)  # même nom : remplacé, pas dupliqué
        self.assertIn("Village : X 5 Y 70 Z 9", c.consulter()["lieux"][1])

    def test_rappels(self):
        c = Carnet(None)
        self.assertIn("10 minutes", c.creer_rappel("replanter les arbres", 10)["resultat"])
        self.assertIn("erreur", c.creer_rappel("x", "bientôt"))
        self.assertEqual(c.rappels_echus(), [])
        self.assertEqual(c.rappels_echus(time.time() + 601), ["replanter les arbres"])
        self.assertEqual(c.donnees["rappels"], [])

    def test_enregistre_et_relu_avec_version_lisible(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "carnet.json"
            c = Carnet(chemin)
            c.noter_projet("Château", "sur la colline")
            c.mettre_resume("Arthur a fondé Valombre.", "2026-10-16T20:00:00")
            relu = Carnet(chemin)
            self.assertEqual(relu.donnees["projets"][0]["nom"], "Château")
            texte = relu.texte()
            self.assertIn("Arthur a fondé Valombre.", texte)
            self.assertIn("- Château : sur la colline", texte)
            self.assertIn("Château", (Path(dossier) / "carnet.md").read_text(encoding="utf-8"))

    def test_fichier_abime(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "carnet.json"
            chemin.write_text("{pas du json", encoding="utf-8")
            with self.assertLogs("compagnon", level="WARNING"):
                self.assertEqual(Carnet(chemin).texte(), "")

    def test_prompt_resume(self):
        c = Carnet(None)
        c.noter_projet("Barrage")
        texte = prompt_resume("Arthur", c, "- mort : noyé")
        self.assertIn("Arthur", texte)
        self.assertIn("Barrage", texte)
        self.assertIn("noyé", texte)


class TestOutils(unittest.TestCase):
    def test_declarations_au_format_du_sdk(self):
        noms = [d.name for d in declarations(types)]
        self.assertIn("creer_rappel", noms)
        self.assertIn("chercher_wiki", noms)
        self.assertNotIn("chercher_wiki", [d.name for d in declarations(types, avec_wiki=False)])
        rappel = next(d for d in declarations(types) if d.name == "creer_rappel")
        self.assertEqual(rappel.parameters.required, ["texte", "minutes"])

    def test_noter_lieu_prend_la_position_du_capteur(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier) / "etat.json"
            chemin.write_text(json.dumps({"horodatage": int(time.time() * 1000), "joueur": {
                "x": 10.2, "y": 64, "z": -5.7, "dimension": "minecraft:overworld"}}), encoding="utf-8")
            capteur = CapteurEtat(chemin)
            capteur.lire()
            outils = Outils(Carnet(None), capteur)
            with self.assertLogs("compagnon", level="INFO"):
                r = asyncio.run(outils.executer("noter_lieu", {"nom": "Base"}))
            self.assertIn("X 10 Y 64 Z -6", r["resultat"])

    def test_outil_inconnu_ou_en_erreur(self):
        outils = Outils(Carnet(None), wiki_actif=False)
        with self.assertLogs("compagnon", level="INFO"):
            self.assertIn("erreur", asyncio.run(outils.executer("chercher_wiki", {"sujet": "balise"})))
            self.assertIn("erreur", asyncio.run(outils.executer("lancer_fusee", {})))
            with mock.patch.object(Carnet, "consulter", side_effect=RuntimeError("boum")):
                self.assertIn("boum", asyncio.run(outils.executer("consulter_carnet", {}))["erreur"])


class TestWiki(unittest.TestCase):
    def test_nettoyage(self):
        texte = wiki.nettoyer_wikitexte(
            "La '''balise''' est un [[bloc]] <ref>source</ref> [[Fichier:Balise.png|vignette|Une [[balise]]]]\n\n"
            "{{Fabrication|A1=Verre|B2=Étoile du Nether|Output=Balise}} [[Catégorie:Blocs]] [[en:Beacon]] "
            "<!-- note -->[[Étoile du Nether|étoile]]")
        self.assertIn("La balise est un bloc", texte)
        self.assertIn("{{Fabrication|A1=Verre|B2=Étoile du Nether|Output=Balise}}", texte)
        self.assertIn("étoile", texte)
        for absent in ("ref", "Fichier", "Catégorie", "Beacon", "note", "'''"):
            self.assertNotIn(absent, texte)

    def test_recherche(self):
        reponses = [{"query": {"search": [{"title": "Balise"}, {"title": "Pyramide"}]}},
                    {"parse": {"title": "Balise", "wikitext": "Une '''balise''' demande 3 [[obsidienne]]s."}}]
        with mock.patch.object(wiki, "_api", side_effect=reponses) as api:
            r = wiki.chercher("balise")
        self.assertEqual(r["page"], "Balise")
        self.assertIn("Une balise demande 3 obsidiennes.", r["contenu"])
        self.assertEqual(r["autres_pages"], ["Pyramide"])
        self.assertEqual(api.call_args_list[1].kwargs["page"], "Balise")

    def test_rien_trouve_ou_hors_ligne(self):
        with mock.patch.object(wiki, "_api", return_value={"query": {"search": []}}):
            self.assertIn("aucune page", wiki.chercher("zorglub")["resultat"])
        with mock.patch.object(wiki, "_api", side_effect=OSError("pas de réseau")):
            self.assertIn("inaccessible", wiki.chercher("balise")["erreur"])


class TestOutilsDansLive(unittest.TestCase):
    def test_config_et_consignes(self):
        config = construire_config(types, config_test(), "c")
        noms = [d.name for d in config.tools[0].function_declarations]
        self.assertIn("ajouter_quete", noms)
        self.assertIsNone(construire_config(types, config_test(outils=False), "c").tools)
        consignes = construire_consignes(config_test(), "perso", "", "", carnet="Projets en cours :\n- Port")
        self.assertIn("creer_rappel", consignes)
        self.assertIn("chercher_wiki", consignes)
        self.assertIn("- Port", consignes)
        sans = construire_consignes(config_test(quetes=False, wiki=False), "perso", "")
        self.assertNotIn("ajouter_quete", sans)
        self.assertNotIn("chercher_wiki", sans)
        self.assertNotIn("creer_rappel", construire_consignes(config_test(outils=False), "perso", ""))

    def test_appel_d_outil_execute_et_reponse_renvoyee(self):
        async def scenario():
            c = creer()
            appel = types.FunctionCall(id="appel-1", name="noter_projet",
                                       args={"nom": "Tour de guet", "details": "sur la falaise"})
            with self.assertLogs("compagnon", level="INFO") as journaux:
                c._traiter(types.LiveServerMessage(tool_call=types.LiveServerToolCall(function_calls=[appel])))
                for tache in list(c._taches):
                    await tache
            return c, journaux.output

        c, journaux = asyncio.run(scenario())
        self.assertEqual(c.carnet.donnees["projets"][0]["nom"], "Tour de guet")
        reponse, = c._session.reponses_outils
        self.assertEqual((reponse.id, reponse.name), ("appel-1", "noter_projet"))
        self.assertIn("noté", reponse.response["resultat"])
        self.assertTrue(any("[Carnet] noter_projet" in l for l in journaux))

    def test_rappel_echu_envoye_au_modele(self):
        async def scenario():
            c = creer()
            c.carnet.donnees["rappels"].append({"texte": "aller manger", "echeance": time.time() - 1})
            with mock.patch("compagnon_ia.live.PERIODE_RAPPELS", 0.01), self.assertLogs("compagnon", level="INFO"):
                tache = asyncio.create_task(c._boucle_rappels())
                for _ in range(200):
                    await asyncio.sleep(0.01)
                    if not c._file_envoi.empty():
                        break
                await asyncio.sleep(0.05)  # le rappel n'est envoyé qu'une fois
            tache.cancel()
            return list(c._file_envoi._queue)

        textes = asyncio.run(scenario())
        self.assertEqual(len(textes), 1)
        self.assertTrue(textes[0][1].startswith("[Rappel]") and "aller manger" in textes[0][1])
        self.assertFalse(textes[0][2])  # pas un commentaire spontané : il doit parler

    def test_coup_d_oeil_rappelle_la_quete(self):
        c = creer()
        self.assertNotIn("Quête", c._texte_coup_d_oeil())
        c.carnet.ajouter_quete("Le phare", "construire un phare sur la côte")
        self.assertIn("« Le phare » (construire un phare sur la côte)", c._texte_coup_d_oeil())

    def test_resume_automatique(self):
        class FauxModeles:
            def __init__(self):
                self.demandes = []

            async def generate_content(self, model, contents):
                self.demandes.append((model, contents))
                return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
                    role="model", parts=[types.Part(text="Arthur a bâti un port et s'est noyé deux fois.")]))])

        class FauxClient:
            def __init__(self):
                self.aio = type("Aio", (), {})()
                self.aio.models = FauxModeles()

        async def scenario():
            c = creer()
            c.client = FauxClient()
            self.assertFalse(await c._resumer())  # trop peu de nouveaux souvenirs
            for texte in ("s'est noyé", "a fini le port", "s'est encore noyé"):
                c.souvenirs.ajouter("mort", texte)
            with self.assertLogs("compagnon", level="INFO"):
                self.assertTrue(await c._resumer())
            self.assertFalse(await c._resumer())  # rien de nouveau depuis
            return c

        c = asyncio.run(scenario())
        self.assertEqual(c.carnet.donnees["resume"], "Arthur a bâti un port et s'est noyé deux fois.")
        modele, prompt = c.client.aio.models.demandes[0]
        self.assertEqual(modele, "gemini-3.5-flash")
        self.assertIn("a fini le port", prompt)
        self.assertIn("Histoire du royaume jusqu'ici", c._construire_consignes())


class TestSouvenirsDepuis(unittest.TestCase):
    def test_depuis(self):
        s = Souvenirs(None)
        s.elements = [{"quand": "2026-10-16T20:00", "genre": "mort", "texte": "a"},
                      {"quand": "2026-10-16T20:05:10", "genre": "progres", "texte": "b"}]
        nouveaux, texte = s.depuis("2026-10-16T20:01:00")
        self.assertEqual([e["texte"] for e in nouveaux], ["b"])
        self.assertIn("progrès : b", texte)
        self.assertEqual(len(s.depuis("")[0]), 2)


if __name__ == "__main__":
    unittest.main()
