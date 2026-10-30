#!/usr/bin/env python3
"""Met à jour la rubrique « Actualités » du site à partir d'Instagram.

Lancé chaque jour par GitHub (voir .github/workflows/instagram.yml).
- interroge l'API d'Instagram avec le jeton rangé dans le secret INSTAGRAM_TOKEN ;
- garde les 2 dernières affiches (photos ou carrousels) et les 2 dernières vidéos ;
- télécharge leurs images dans images/instagram/ (le site n'appelle jamais Instagram
  directement : aucun cookie, aucun script de Meta chez les visiteurs) ;
- réécrit la rubrique entre les repères INSTAGRAM:DEBUT et INSTAGRAM:FIN de index.html.

En cas d'erreur, le message est écrit dans .github/instagram-erreur.txt (sans le jeton),
et le site garde la dernière version publiée.
"""

import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

COMPTE_ID = "17841428811962553"          # @intuition_tango
NB_AFFICHES = 2
NB_VIDEOS = 2

RACINE = Path(__file__).resolve().parent.parent
PAGE = RACINE / "index.html"
DOSSIER_IMAGES = RACINE / "images" / "instagram"
ETAT = DOSSIER_IMAGES / "etat.json"
FICHIER_ERREUR = RACINE / ".github" / "instagram-erreur.txt"
DEBUT = "<!-- INSTAGRAM:DEBUT -->"
FIN = "<!-- INSTAGRAM:FIN -->"

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
        "juil.", "août", "sept.", "oct.", "nov.", "déc."]

JETON = os.environ.get("INSTAGRAM_TOKEN", "").strip()


def masquer(texte):
    return texte.replace(JETON, "***") if JETON else texte


def appel_api(chemin, **params):
    params["access_token"] = JETON
    url = f"https://graph.facebook.com/{chemin}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as reponse:
            return json.load(reponse)
    except urllib.error.HTTPError as e:
        corps = e.read().decode("utf-8", "replace")
        raise RuntimeError(f"Instagram a répondu {e.code} : {corps}") from None


def telecharger(url, destination):
    requete = urllib.request.Request(url, headers={"User-Agent": "intuitiontango.fr"})
    with urllib.request.urlopen(requete, timeout=60) as reponse:
        destination.write_bytes(reponse.read())


def image_de(media):
    """Renvoie l'URL de l'image à afficher pour une publication, ou None."""
    if media["media_type"] == "VIDEO":
        return media.get("thumbnail_url")
    if media["media_type"] == "IMAGE":
        return media.get("media_url")
    # Carrousel : première image du carrousel (ou vignette de la première vidéo)
    for enfant in media.get("children", {}).get("data", []):
        if enfant.get("media_type") == "IMAGE" and enfant.get("media_url"):
            return enfant["media_url"]
        if enfant.get("thumbnail_url"):
            return enfant["thumbnail_url"]
    return media.get("media_url")


def date_fr(horodatage):
    d = datetime.strptime(horodatage[:10], "%Y-%m-%d")
    return f"{d.day} {MOIS[d.month - 1]}", d.strftime("%Y-%m-%d")


def legende_courte(media, longueur=110):
    texte = " ".join((media.get("caption") or "").split())
    if len(texte) > longueur:
        texte = texte[:longueur].rsplit(" ", 1)[0] + "…"
    return texte


def carte(media, fichier, est_video):
    jour, iso = date_fr(media["timestamp"])
    legende = legende_courte(media)
    nature = "Vidéo" if est_video else "Affiche"
    alt = f"{nature} Instagram : {legende}" if legende else f"{nature} Instagram d'Intuition Tango"
    lecture = '<span class="lecture" aria-hidden="true">▶</span>' if est_video else ""
    classe = "insta-visuel insta-video" if est_video else "insta-visuel"
    return f"""          <li>
            <a class="insta-carte" href="{html.escape(media['permalink'])}" rel="noopener">
              <span class="{classe}"><img src="images/instagram/{fichier}" alt="{html.escape(alt)}" width="540" height="675" loading="lazy">{lecture}</span>
              <span class="insta-meta"><span class="type">{nature}</span> · <time datetime="{iso}">{jour}</time></span>
            </a>
          </li>"""


def rubrique(cartes):
    if not cartes:
        return ""
    return f"""
  <!-- ===================== ACTUALITÉS (générée automatiquement depuis Instagram : ne pas modifier à la main) ===================== -->
  <section class="bloc" id="actualites">
    <div class="contenu">
      <h2>Actualités</h2>
      <p class="intro">Nos dernières affiches et vidéos, publiées sur <a href="https://www.instagram.com/intuition_tango/" rel="noopener">Instagram</a>.</p>
      <ul class="insta">
{chr(10).join(cartes)}
      </ul>
      <p class="tarifs"><a class="bouton bouton-ligne" href="https://www.instagram.com/intuition_tango/" rel="noopener">Suivre @intuition_tango</a></p>
    </div>
  </section>
"""


def principal():
    if not JETON:
        raise RuntimeError("Le secret INSTAGRAM_TOKEN est vide ou absent.")

    reponse = appel_api(
        f"{COMPTE_ID}/media",
        fields="id,media_type,media_url,thumbnail_url,permalink,timestamp,caption,"
               "children{media_type,media_url,thumbnail_url}",
        limit=40,
    )
    medias = reponse.get("data", [])

    affiches, videos = [], []
    for m in medias:  # l'API renvoie les publications de la plus récente à la plus ancienne
        if not m.get("permalink") or not image_de(m):
            continue
        if m["media_type"] == "VIDEO":
            if len(videos) < NB_VIDEOS:
                videos.append(m)
        elif len(affiches) < NB_AFFICHES:
            affiches.append(m)

    choix = [(m, False) for m in affiches] + [(m, True) for m in videos]
    ids = [m["id"] for m, _ in choix]

    # Rien de nouveau depuis la dernière fois : on ne touche à rien.
    if ETAT.exists() and json.loads(ETAT.read_text()).get("ids") == ids:
        print("Aucune nouvelle publication.")
        return

    DOSSIER_IMAGES.mkdir(parents=True, exist_ok=True)
    for ancien in DOSSIER_IMAGES.glob("*.jpg"):
        ancien.unlink()

    cartes = []
    for m, est_video in choix:
        fichier = f"{m['id']}.jpg"
        telecharger(image_de(m), DOSSIER_IMAGES / fichier)
        cartes.append(carte(m, fichier, est_video))

    page = PAGE.read_text(encoding="utf-8")
    avant, reste = page.split(DEBUT, 1)
    _, apres = reste.split(FIN, 1)
    PAGE.write_text(avant + DEBUT + rubrique(cartes) + "  " + FIN + apres, encoding="utf-8")

    ETAT.write_text(json.dumps({"ids": ids}, indent=2) + "\n")
    print(f"Rubrique mise à jour : {len(affiches)} affiche(s), {len(videos)} vidéo(s).")


if __name__ == "__main__":
    try:
        principal()
        FICHIER_ERREUR.unlink(missing_ok=True)
    except Exception as e:  # noqa: BLE001 — on consigne toute erreur pour la retrouver
        message = masquer(f"{datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n{type(e).__name__} : {e}\n")
        FICHIER_ERREUR.parent.mkdir(exist_ok=True)
        FICHIER_ERREUR.write_text(message, encoding="utf-8")
        print(message, file=sys.stderr)
