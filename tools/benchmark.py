"""
LouLLabs STT — Harnais de benchmark autonome
============================================

Objectif : décider le moteur/backend sur des MESURES, pas sur une intuition.
Il mesure ce qui compte pour la dictée courte :
  - latence "cold start"  (modèle non chargé -> texte)
  - latence "warm start"  (modèle déjà en mémoire -> texte)
  - qualité  (WER, Word Error Rate) vs le texte réellement lu
Le corpus couvre : français courant / rapide / lent, voix faible, chiffres,
noms propres, ponctuation, phrases longues, léger bruit, silence complet.

Cet outil est SÉPARÉ de l'application (il n'alourdit pas LouLLabs STT).

Usage :
    python tools/benchmark.py            # enregistre le corpus (si absent) puis mesure
    python tools/benchmark.py --record   # (ré)enregistre le corpus
    python tools/benchmark.py --run      # mesure sur le corpus déjà enregistré
    python tools/benchmark.py --model small --compute int8

Architecture backend : `run_backend("cpu", ...)` fonctionne aujourd'hui.
Les backends GPU (`vulkan`, `rocm` via whisper.cpp) sont des points d'extension
volontairement laissés en TODO — à brancher APRÈS ce benchmark, pas avant.
"""

import os
import sys
import time
import json
import wave
import argparse

import numpy as np

SAMPLE_RATE = 16000
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "benchmark_data")

# Corpus : (id, categorie, texte de reference a lire a voix haute)
PROMPTS = [
    ("courant",     "Français courant",  "Bonjour, je teste la dictée vocale et j'aimerais voir si elle fonctionne correctement."),
    ("rapide",      "Français rapide",   "Il faut vraiment que je me dépêche parce que le train part dans cinq minutes."),
    ("lent",        "Français lent",     "Je parle... très... lentement... pour tester... la transcription."),
    ("chiffres",    "Chiffres",          "Le total est de mille deux cent quarante-sept euros et trente-huit centimes."),
    ("noms",        "Noms propres",      "Loïc travaille chez LouLLabs à Paris et à Barcelone."),
    ("ponctuation", "Ponctuation",       "Attends, tu es sûr ? Oui, absolument ! On y va."),
    ("longue",      "Phrase longue",     "Quand j'appuie sur la touche puis que je relâche, le texte doit apparaître immédiatement là où se trouve mon curseur, sans que je perde ce que j'avais copié auparavant."),
    ("silence",     "Silence complet",   ""),   # ne rien dire : doit produire une transcription vide/filtrée
]


# ── Normalisation + WER ─────────────────────────────────────────
import re, unicodedata

def normalize(s: str):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]+", " ", s)).strip()

def wer(ref: str, hyp: str) -> float:
    r = normalize(ref).split()
    h = normalize(hyp).split()
    if not r:
        return 0.0 if not h else 1.0
    # distance d'edition (mots)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = d[j]
            d[j] = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return d[len(h)] / len(r)


# ── Enregistrement du corpus ────────────────────────────────────
def record_corpus():
    import sounddevice as sd
    os.makedirs(DATA_DIR, exist_ok=True)
    print("\n=== Enregistrement du corpus ===")
    print("Pour chaque phrase : appuyez sur Entrée, lisez, puis Entrée pour arrêter.\n")
    for pid, cat, ref in PROMPTS:
        print(f"[{cat}]")
        if ref:
            print(f'  Lisez : "{ref}"')
        else:
            print("  (NE DITES RIEN — test du silence)")
        input("  Entrée pour démarrer...")
        chunks = []
        stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                                callback=lambda indata, *_: chunks.append(indata.copy()))
        stream.start()
        input("  ... enregistrement, Entrée pour arrêter.")
        stream.stop(); stream.close()
        audio = (np.concatenate(chunks).flatten() if chunks
                 else np.zeros(SAMPLE_RATE, dtype="float32"))
        _save_wav(os.path.join(DATA_DIR, f"{pid}.wav"), audio)
        with open(os.path.join(DATA_DIR, f"{pid}.txt"), "w", encoding="utf-8") as f:
            f.write(ref)
        print(f"  OK ({len(audio) / SAMPLE_RATE:.1f}s)\n")
    print("Corpus enregistré dans", DATA_DIR, "\n")


def _save_wav(path, audio_f32):
    pcm = np.clip(audio_f32, -1, 1)
    pcm = (pcm * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def _load_wav(path):
    with wave.open(path, "rb") as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return (pcm.astype(np.float32) / 32768.0)


def load_corpus():
    samples = []
    for pid, cat, _ in PROMPTS:
        wav = os.path.join(DATA_DIR, f"{pid}.wav")
        txt = os.path.join(DATA_DIR, f"{pid}.txt")
        if not os.path.exists(wav):
            return None
        ref = open(txt, encoding="utf-8").read() if os.path.exists(txt) else ""
        samples.append((pid, cat, ref, _load_wav(wav)))
    return samples


# ── Backends ────────────────────────────────────────────────────
def run_backend(name, samples, model_size, compute):
    """Retourne dict {cold_s, results:[{id,cat,latency_s,wer,text}], warm_median, wer_mean}."""
    if name == "cpu":
        return _run_faster_whisper(samples, model_size, compute, device="cpu")
    if name == "cuda":       # NVIDIA
        return _run_faster_whisper(samples, model_size, compute, device="cuda")
    if name in ("vulkan", "rocm"):
        # TODO (vague 2) : brancher whisper.cpp (Vulkan / ROCm) ici, meme interface.
        # Voir https://github.com/ggml-org/whisper.cpp (backends Vulkan / HIP).
        raise NotImplementedError(f"Backend '{name}' a brancher (whisper.cpp).")
    raise ValueError(f"Backend inconnu : {name}")


def _run_faster_whisper(samples, model_size, compute, device):
    from faster_whisper import WhisperModel

    def transcribe(model, audio):
        segs, _ = model.transcribe(audio, language="fr", beam_size=3,
                                   vad_filter=True,
                                   vad_parameters=dict(min_silence_duration_ms=500),
                                   without_timestamps=True, no_speech_threshold=0.6)
        return " ".join(s.text.strip() for s in segs if s.text.strip()).strip()

    # Cold start : chargement + 1re transcription
    t0 = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute,
                         cpu_threads=max(1, (os.cpu_count() or 2) // 2), num_workers=1)
    _ = transcribe(model, samples[0][3])
    cold = time.perf_counter() - t0

    # Warm : chaque echantillon, modele deja pret
    results, lat = [], []
    for pid, cat, ref, audio in samples:
        t = time.perf_counter()
        text = transcribe(model, audio)
        dt = time.perf_counter() - t
        lat.append(dt)
        results.append({"id": pid, "cat": cat, "latency_s": round(dt, 3),
                        "wer": round(wer(ref, text), 3), "text": text, "ref": ref})
    spoken = [r for r in results if r["ref"]]
    return {
        "backend": device, "model": model_size, "compute": compute,
        "cold_start_s": round(cold, 2),
        "warm_median_s": round(float(np.median(lat)), 3),
        "warm_p95_s": round(float(np.percentile(lat, 95)), 3),
        "wer_mean": round(float(np.mean([r["wer"] for r in spoken])) if spoken else 0.0, 3),
        "results": results,
    }


# ── Rapport ─────────────────────────────────────────────────────
def report(res):
    print("\n" + "=" * 68)
    print(f"  Backend : {res['backend']}   Modele : {res['model']} ({res['compute']})")
    print("=" * 68)
    print(f"  Cold start      : {res['cold_start_s']:.2f} s")
    print(f"  Latence mediane : {res['warm_median_s']:.3f} s   (p95 {res['warm_p95_s']:.3f} s)")
    print(f"  WER moyen       : {res['wer_mean'] * 100:.1f} %")
    print("-" * 68)
    print(f"  {'Categorie':<20}{'Latence':>10}{'WER':>8}   Texte")
    for r in res["results"]:
        w = "-" if not r["ref"] else f"{r['wer'] * 100:.0f}%"
        print(f"  {r['cat']:<20}{r['latency_s']:>9.3f}s{w:>8}   {r['text'][:40]}")
    print("=" * 68)
    out = os.path.join(DATA_DIR, f"result_{res['backend']}_{res['model']}.json")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print("  Rapport JSON :", out, "\n")


def main():
    ap = argparse.ArgumentParser(description="Benchmark LouLLabs STT")
    ap.add_argument("--record", action="store_true", help="(ré)enregistrer le corpus")
    ap.add_argument("--run", action="store_true", help="mesurer sur le corpus existant")
    ap.add_argument("--backend", default="cpu", help="cpu | cuda | vulkan | rocm")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--compute", default="int8")
    args = ap.parse_args()

    if args.record or (not args.run and load_corpus() is None):
        record_corpus()

    samples = load_corpus()
    if samples is None:
        print("Corpus absent. Lancez d'abord :  python tools/benchmark.py --record")
        sys.exit(1)

    try:
        res = run_backend(args.backend, samples, args.model, args.compute)
    except NotImplementedError as e:
        print(f"\n{e}\n(Backend a implementer en vague 2 — voir le TODO dans run_backend.)")
        sys.exit(2)
    report(res)


if __name__ == "__main__":
    main()
