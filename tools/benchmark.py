"""
LouLLabs STT — Harnais de benchmark autonome (v2)
=================================================

Décider le moteur/backend sur des MESURES, pas sur une intuition. Il mesure ce
qui compte pour la dictée courte :

  - latence "cold start"     (modèle non chargé -> texte)
  - latence "warm start"     P50 / P95 sur N répétitions (la STABILITÉ compte
                             autant que la moyenne)
  - latence PERÇUE           inférence + insertion (F8 relâché -> texte visible)
  - qualité                  WER (Word Error Rate) vs le texte réellement lu
  - contrôle du filtre       aucune vraie phrase courte ne doit être "mangée"
                             (faux positif), le silence doit être filtré

Le corpus est réparti par LONGUEUR (micro / court / moyen / long) car le
comportement CPU vs GPU peut être radicalement différent selon la durée.

Cet outil est SÉPARÉ de l'application (il n'alourdit pas LouLLabs STT).

Usage :
    python tools/benchmark.py                 # enregistre le manquant puis mesure
    python tools/benchmark.py --record        # (ré)enregistrer Tout le corpus
    python tools/benchmark.py --run           # mesurer sur le corpus existant
    python tools/benchmark.py --repeats 5 --insert frappe
    python tools/benchmark.py --backend cpu --model large-v3-turbo --compute int8

Backends : `cpu` et `cuda` fonctionnent. `vulkan` / `rocm` (whisper.cpp) sont
des points d'extension laissés en TODO — à brancher APRÈS ce benchmark.
"""

import os
import sys
import time
import json
import wave
import argparse
import re
import unicodedata

import numpy as np

SAMPLE_RATE = 16000
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmark_data")

# Corpus : id, catégorie, classe de longueur, référence, attendu.
#   expect="text"   -> DOIT être écrit (un filtrage = FAUX POSITIF, grave)
#   expect="filter" -> DOIT être filtré (silence)
# Les "micro" servent aussi de contrôle anti-faux-positifs (mots courts réels).
PROMPTS = [
    # --- micro (1-2 mots) : ne doivent JAMAIS être filtrés ---
    dict(id="m_oui",   cat="Micro : oui",    cls="micro", expect="text",   ref="oui"),
    dict(id="m_non",   cat="Micro : non",    cls="micro", expect="text",   ref="non"),
    dict(id="m_ok",    cat="Micro : ok",     cls="micro", expect="text",   ref="ok"),
    dict(id="m_merci", cat="Micro : merci",  cls="micro", expect="text",   ref="merci"),
    dict(id="m_test",  cat="Micro : test",   cls="micro", expect="text",   ref="test"),
    dict(id="m_court", cat="Micro : à demain", cls="micro", expect="text", ref="à demain"),
    # --- court (3-10 s) ---
    dict(id="courant",     cat="Courant",     cls="court", expect="text",
         ref="Bonjour, je teste la dictée vocale et j'aimerais voir si elle fonctionne correctement."),
    dict(id="rapide",      cat="Rapide",      cls="court", expect="text",
         ref="Il faut vraiment que je me dépêche parce que le train part dans cinq minutes."),
    dict(id="chiffres",    cat="Chiffres",    cls="court", expect="text",
         ref="Le total est de mille deux cent quarante-sept euros et trente-huit centimes."),
    dict(id="noms",        cat="Noms propres", cls="court", expect="text",
         ref="Loïc travaille chez LouLLabs à Paris et à Barcelone."),
    dict(id="ponctuation", cat="Ponctuation", cls="court", expect="text",
         ref="Attends, tu es sûr ? Oui, absolument ! On y va."),
    # --- moyen (10-30 s) ---
    dict(id="lent",        cat="Lent",        cls="moyen", expect="text",
         ref="Je parle... très... lentement... pour tester... la transcription."),
    dict(id="longue",      cat="Phrase longue", cls="moyen", expect="text",
         ref="Quand j'appuie sur la touche puis que je relâche, le texte doit apparaître immédiatement là où se trouve mon curseur, sans que je perde ce que j'avais copié auparavant."),
    # --- long (30-60 s) ---
    dict(id="long",        cat="Long (paragraphe)", cls="long", expect="text",
         ref="Je vais lire un paragraphe assez long afin de mesurer le comportement du moteur "
             "sur une dictée continue. L'objectif n'est pas de transcrire des heures d'audio, "
             "mais de vérifier que la latence et la qualité restent stables quand je parle "
             "pendant une trentaine de secondes sans m'arrêter, en articulant normalement, "
             "avec quelques chiffres comme douze, quarante-huit et deux mille vingt-six."),
    # --- silence : DOIT être filtré ---
    dict(id="silence",     cat="Silence complet", cls="silence", expect="filter", ref=""),
]

# ── Réglages du filtre (miroir de l'app) ────────────────────────
SILENCE_RMS = 0.006
BLOCKLIST = None  # rempli plus bas

def _normalize(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]+", " ", s)).strip()

BLOCKLIST = {_normalize(x) for x in [
    "Sous-titres realises par la communaute d'Amara.org",
    "Sous-titrage ST' 501",
    "Merci d'avoir regarde cette video",
    "Thank you for watching",
]}

def wer(ref, hyp):
    r = _normalize(ref).split(); h = _normalize(hyp).split()
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / len(r)

def should_suppress(text, audio, m):
    n = _normalize(text)
    if not n:
        return True
    if n in BLOCKLIST:
        return True
    if m["cr"] > 2.5:
        return True
    if m["ns"] > 0.85 and m["lp"] < -1.0:
        return True
    rms = float(np.sqrt(np.mean(np.square(audio))))
    if rms < SILENCE_RMS and m["lp"] < -0.8 and len(n) < 40:
        return True
    return False

def insertion_ms(text, method):
    """Coût d'insertion PERÇU (modélisé, cohérent avec l'app)."""
    if method == "collage":
        return 120.0                      # sleep avant Ctrl+V (fixe)
    return min(len(text) * 0.6, 60.0)     # frappe Unicode SendInput ~ proportionnel, plafonné


# ── Enregistrement (seulement les échantillons manquants) ───────
def record_missing(force=False):
    import sounddevice as sd
    os.makedirs(DATA_DIR, exist_ok=True)
    todo = [p for p in PROMPTS
            if force or not os.path.exists(os.path.join(DATA_DIR, p["id"] + ".wav"))]
    if not todo:
        return
    print(f"\n=== Enregistrement ({len(todo)} échantillon(s)) ===")
    print("Pour chaque phrase : Entrée pour démarrer, lisez, Entrée pour arrêter.\n")
    for p in todo:
        print(f"[{p['cat']}]  ({p['cls']})")
        print(f'  Lisez : "{p["ref"]}"' if p["ref"] else "  (NE DITES RIEN — test du silence)")
        input("  Entrée pour démarrer...")
        chunks = []
        st = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            callback=lambda indata, *_: chunks.append(indata.copy()))
        st.start(); input("  ... enregistrement, Entrée pour arrêter."); st.stop(); st.close()
        audio = (np.concatenate(chunks).flatten() if chunks
                 else np.zeros(SAMPLE_RATE, dtype="float32"))
        _save_wav(os.path.join(DATA_DIR, p["id"] + ".wav"), audio)
        with open(os.path.join(DATA_DIR, p["id"] + ".txt"), "w", encoding="utf-8") as f:
            f.write(p["ref"])
        print(f"  OK ({len(audio) / SAMPLE_RATE:.1f}s)\n")

def _save_wav(path, a):
    pcm = (np.clip(a, -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(pcm.tobytes())

def _load_wav(path):
    with wave.open(path, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0

def load_corpus():
    out = []
    for p in PROMPTS:
        wav = os.path.join(DATA_DIR, p["id"] + ".wav")
        if not os.path.exists(wav):
            return None
        out.append((p, _load_wav(wav)))
    return out


# ── Backends ────────────────────────────────────────────────────
def run_backend(name, corpus, model_size, compute, repeats, method):
    if name in ("cpu", "cuda"):
        return _run_faster_whisper(corpus, model_size, compute, name, repeats, method)
    if name in ("vulkan", "rocm"):
        # TODO (vague 2) : brancher whisper.cpp (Vulkan / ROCm) ici, MÊME interface.
        # https://github.com/ggml-org/whisper.cpp  (backends Vulkan / HIP)
        raise NotImplementedError(f"Backend '{name}' à brancher (whisper.cpp).")
    raise ValueError(f"Backend inconnu : {name}")

def _run_faster_whisper(corpus, model_size, compute, device, repeats, method):
    from faster_whisper import WhisperModel

    def transcribe(model, audio):
        segs, _ = model.transcribe(audio, language="fr", beam_size=3, vad_filter=True,
                                   vad_parameters=dict(min_silence_duration_ms=500),
                                   without_timestamps=True, no_speech_threshold=0.6)
        parts, ns, lp, cr = [], [], [], []
        for s in segs:
            if s.text.strip():
                parts.append(s.text.strip())
            ns.append(float(getattr(s, "no_speech_prob", 0.0)))
            lp.append(float(getattr(s, "avg_logprob", 0.0)))
            cr.append(float(getattr(s, "compression_ratio", 1.0)))
        text = " ".join(parts).strip()
        m = {"ns": (sum(ns) / len(ns)) if ns else 1.0,
             "lp": (sum(lp) / len(lp)) if lp else -10.0,
             "cr": max(cr) if cr else 1.0}
        return text, m

    t0 = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute,
                         cpu_threads=max(1, (os.cpu_count() or 2) // 2), num_workers=1)
    transcribe(model, corpus[0][1])
    cold = time.perf_counter() - t0

    rows = []
    for p, audio in corpus:
        lats = []
        text, m = "", {}
        for _ in range(repeats):
            t = time.perf_counter()
            text, m = transcribe(model, audio)
            lats.append((time.perf_counter() - t) * 1000.0)  # ms
        sup = should_suppress(text, audio, m)
        w = wer(p["ref"], text) if (p["expect"] == "text" and p["ref"]) else None
        rows.append(dict(p=p, text=text, lat_ms=lats, suppressed=sup, wer=w,
                         perceived_ms=float(np.median(lats)) + insertion_ms(text, method)))
    return dict(backend=device, model=model_size, compute=compute, repeats=repeats,
                method=method, cold_start_s=round(cold, 2), rows=rows)


# ── Rapport ─────────────────────────────────────────────────────
def report(res):
    rows = res["rows"]
    print("\n" + "=" * 72)
    print(f"  Backend {res['backend']} · modèle {res['model']} ({res['compute']}) · "
          f"{res['repeats']} rép. · insertion « {res['method']} »")
    print("=" * 72)
    print(f"  Cold start : {res['cold_start_s']:.2f} s\n")

    # Latence + WER par classe de longueur
    print(f"  {'Classe':<10}{'n':>3}{'P50':>9}{'P95':>9}{'perçu P50':>12}{'WER moy':>10}")
    for cls in ["micro", "court", "moyen", "long"]:
        rs = [r for r in rows if r["p"]["cls"] == cls]
        if not rs:
            continue
        all_lat = [x for r in rs for x in r["lat_ms"]]
        perc = [r["perceived_ms"] for r in rs]
        wl = [r["wer"] for r in rs if r["wer"] is not None]
        p50 = np.median(all_lat); p95 = np.percentile(all_lat, 95)
        wtxt = f"{np.mean(wl) * 100:.1f}%" if wl else "-"
        print(f"  {cls:<10}{len(rs):>3}{p50:>8.0f}ms{p95:>8.0f}ms"
              f"{np.median(perc):>10.0f}ms{wtxt:>10}")

    # Contrôle du filtre : faux positifs / faux négatifs
    print("\n  Contrôle du filtre (faux positif = vraie phrase supprimée = GRAVE)")
    fp = fn = 0
    for r in rows:
        exp = r["p"]["expect"]
        if exp == "text" and r["suppressed"]:
            verdict = "❌ FAUX POSITIF"; fp += 1
        elif exp == "filter" and not r["suppressed"]:
            verdict = "⚠️  faux négatif"; fn += 1
        else:
            verdict = "✓"
        print(f"    {verdict:<16} {r['p']['cat']:<22} -> {r['text'][:42]!r}")
    print(f"\n  Bilan filtre : {fp} faux positif(s), {fn} faux négatif(s).")
    if fp:
        print("  ⚠️  Au moins une vraie phrase a été filtrée : desserrer les seuils.")

    out = os.path.join(DATA_DIR, f"result_{res['backend']}_{res['model']}.json")
    serial = dict(res); serial["rows"] = [
        dict(id=r["p"]["id"], cls=r["p"]["cls"], expect=r["p"]["expect"],
             text=r["text"], wer=r["wer"], suppressed=r["suppressed"],
             lat_ms=[round(x, 1) for x in r["lat_ms"]],
             perceived_ms=round(r["perceived_ms"], 1)) for r in rows]
    with open(out, "w", encoding="utf-8") as f:
        json.dump(serial, f, indent=2, ensure_ascii=False)
    print("\n  Rapport JSON :", out)
    print("\n  Décision : ne pas choisir « le plus rapide » mais « la meilleure")
    print("  expérience globale » = latence perçue P50/P95 + WER + stabilité +")
    print("  cold start + ressources. Comparez ce JSON entre backends.\n")


def main():
    ap = argparse.ArgumentParser(description="Benchmark LouLLabs STT")
    ap.add_argument("--record", action="store_true", help="(ré)enregistrer TOUT le corpus")
    ap.add_argument("--run", action="store_true", help="mesurer sans (ré)enregistrer")
    ap.add_argument("--backend", default="cpu", help="cpu | cuda | vulkan | rocm")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--repeats", type=int, default=3, help="répétitions pour P50/P95")
    ap.add_argument("--insert", default="frappe", choices=["frappe", "collage"])
    args = ap.parse_args()

    if args.record:
        record_missing(force=True)
    elif not args.run:
        record_missing(force=False)   # enregistre uniquement le manquant

    corpus = load_corpus()
    if corpus is None:
        print("Corpus incomplet. Lancez :  python tools/benchmark.py --record")
        sys.exit(1)

    try:
        res = run_backend(args.backend, corpus, args.model, args.compute,
                          args.repeats, args.insert)
    except NotImplementedError as e:
        print(f"\n{e}\n(À implémenter en vague 2 — voir le TODO dans run_backend.)")
        sys.exit(2)
    report(res)


if __name__ == "__main__":
    main()
