"""
LouLLabs STT - Standalone benchmark harness (v2)
================================================

Decide the engine/backend based on MEASUREMENTS, not intuition. It measures what
matters for short dictation:

  - "cold start" latency     (model not loaded -> text)
  - "warm start" latency     P50 / P95 over N repetitions (STABILITY matters
                             as much as the average)
  - PERCEIVED latency        inference + insertion (F8 released -> visible text)
  - quality                  WER (Word Error Rate) vs the text actually read
  - filter control           no real short phrase should be "eaten"
                             (false positive), silence must be filtered out

The corpus is split by LENGTH (micro / short / medium / long) because CPU vs GPU
behavior can differ radically depending on duration.

This tool is SEPARATE from the application (it does not bloat LouLLabs STT).

Usage:
    python tools/benchmark.py                 # record what's missing then measure
    python tools/benchmark.py --record        # (re)record the entire corpus
    python tools/benchmark.py --run           # measure on the existing corpus
    python tools/benchmark.py --repeats 5 --insert frappe
    python tools/benchmark.py --backend cpu --model large-v3-turbo --compute int8

Backends: `cpu` and `cuda` work. `vulkan` / `rocm` (whisper.cpp) are
extension points left as TODO - to be wired in AFTER this benchmark.
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

# Corpus: id, category, length class, reference, expected.
#   expect="text"   -> MUST be written (filtering it = FALSE POSITIVE, serious)
#   expect="filter" -> MUST be filtered out (silence)
# The "micro" items also serve as an anti-false-positive control (real short words).
PROMPTS = [
    # --- micro (1-2 words): must NEVER be filtered out ---
    dict(id="m_oui",   cat="Micro: yes",    cls="micro", expect="text",   ref="yes"),
    dict(id="m_non",   cat="Micro: no",     cls="micro", expect="text",   ref="no"),
    dict(id="m_ok",    cat="Micro: ok",     cls="micro", expect="text",   ref="ok"),
    dict(id="m_merci", cat="Micro: thanks", cls="micro", expect="text",   ref="thanks"),
    dict(id="m_test",  cat="Micro: test",   cls="micro", expect="text",   ref="test"),
    dict(id="m_court", cat="Micro: see you tomorrow", cls="micro", expect="text", ref="see you tomorrow"),
    # --- short (3-10 s) ---
    dict(id="courant",     cat="Everyday",    cls="court", expect="text",
         ref="Hello, I'm testing voice dictation and I'd like to see if it works correctly."),
    dict(id="rapide",      cat="Fast",        cls="court", expect="text",
         ref="I really need to hurry because the train leaves in five minutes."),
    dict(id="chiffres",    cat="Numbers",     cls="court", expect="text",
         ref="The total is one thousand two hundred forty-seven dollars and thirty-eight cents."),
    dict(id="noms",        cat="Proper nouns", cls="court", expect="text",
         ref="Loic works at LouLLabs in Paris and Barcelona."),
    dict(id="ponctuation", cat="Punctuation", cls="court", expect="text",
         ref="Wait, are you sure? Yes, absolutely! Let's go."),
    # --- medium (10-30 s) ---
    dict(id="lent",        cat="Slow",        cls="moyen", expect="text",
         ref="I am speaking... very... slowly... to test... the transcription."),
    dict(id="longue",      cat="Long sentence", cls="moyen", expect="text",
         ref="When I press the key and then release it, the text should appear immediately where my cursor is, without me losing what I had copied beforehand."),
    # --- long (30-60 s) ---
    dict(id="long",        cat="Long (paragraph)", cls="long", expect="text",
         ref="I am going to read a fairly long paragraph in order to measure the engine's behavior "
             "on continuous dictation. The goal is not to transcribe hours of audio, "
             "but to verify that latency and quality stay stable when I speak "
             "for around thirty seconds without stopping, articulating normally, "
             "with a few numbers like twelve, forty-eight, and two thousand twenty-six."),
    # --- silence: MUST be filtered out ---
    dict(id="silence",     cat="Complete silence", cls="silence", expect="filter", ref=""),
]

# ── Filter settings (mirror of the app) ─────────────────────────
SILENCE_RMS = 0.006
BLOCKLIST = None  # filled in below

def _normalize(s):
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z ]+", " ", s)).strip()

# Raw model hallucination phrases - kept verbatim to match raw model output.
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
    """PERCEIVED insertion cost (modeled, consistent with the app)."""
    if method == "collage":
        return 120.0                      # sleep before Ctrl+V (fixed)
    return min(len(text) * 0.6, 60.0)     # Unicode SendInput typing ~ proportional, capped


# ── Recording (only the missing samples) ────────────────────────
def record_missing(force=False):
    import sounddevice as sd
    os.makedirs(DATA_DIR, exist_ok=True)
    todo = [p for p in PROMPTS
            if force or not os.path.exists(os.path.join(DATA_DIR, p["id"] + ".wav"))]
    if not todo:
        return
    print(f"\n=== Recording ({len(todo)} sample(s)) ===")
    print("For each phrase: Enter to start, read it, Enter to stop.\n")
    for p in todo:
        print(f"[{p['cat']}]  ({p['cls']})")
        print(f'  Read: "{p["ref"]}"' if p["ref"] else "  (SAY NOTHING - silence test)")
        input("  Enter to start...")
        chunks = []
        st = sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            callback=lambda indata, *_: chunks.append(indata.copy()))
        st.start(); input("  ... recording, Enter to stop."); st.stop(); st.close()
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
def run_backend(name, corpus, model_size, compute, repeats, method, threads=None, beam=3):
    if name in ("cpu", "cuda"):
        return _run_faster_whisper(corpus, model_size, compute, name, repeats,
                                   method, threads, beam)
    if name in ("vulkan", "rocm"):
        # TODO (wave 2): wire up whisper.cpp (Vulkan / ROCm) here, SAME interface.
        # https://github.com/ggml-org/whisper.cpp  (Vulkan / HIP backends)
        raise NotImplementedError(f"Backend '{name}' to be wired up (whisper.cpp).")
    raise ValueError(f"Unknown backend: {name}")

def _run_faster_whisper(corpus, model_size, compute, device, repeats, method,
                        threads=None, beam=3):
    from faster_whisper import WhisperModel

    def transcribe(model, audio):
        segs, _ = model.transcribe(audio, language="en", beam_size=beam, vad_filter=True,
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

    print(f"\nPreparing model « {model_size} » ({compute}) on {device}...")
    print("  ⏳  First launch: downloading ~1.5 GB from Hugging Face.")
    print("      A progress bar will appear - LET IT FINISH (several minutes).\n")
    n_threads = threads if (threads and threads > 0) else max(1, os.cpu_count() or 4)
    print(f"  CPU threads: {n_threads} · beam: {beam}")
    t0 = time.perf_counter()
    model = WhisperModel(model_size, device=device, compute_type=compute,
                         cpu_threads=n_threads, num_workers=1)
    transcribe(model, corpus[0][1])   # 1st inference = "cold start"
    cold = time.perf_counter() - t0
    print(f"  ✓ Model ready (cold start {cold:.1f} s).\n")

    print(f"Measuring {len(corpus)} samples × {repeats} repetition(s):")
    rows = []
    for idx, (p, audio) in enumerate(corpus, 1):
        print(f"  [{idx:>2}/{len(corpus)}] {p['id']:<12} ({p['cls']})", end=" ", flush=True)
        lats, text, m = [], "", {}
        for _ in range(repeats):
            t = time.perf_counter()
            text, m = transcribe(model, audio)
            lats.append((time.perf_counter() - t) * 1000.0)  # ms
        sup = should_suppress(text, audio, m)
        w = wer(p["ref"], text) if (p["expect"] == "text" and p["ref"]) else None
        rows.append(dict(p=p, text=text, lat_ms=lats, suppressed=sup, wer=w,
                         perceived_ms=float(np.median(lats)) + insertion_ms(text, method)))
        wtxt = "-" if w is None else f"WER {w * 100:.0f}%"
        flag = "FILTERED" if sup else "ok"
        if p["expect"] == "text" and sup:
            flag = "⚠️ FALSE POSITIVE"
        print(f"→ {np.median(lats):>5.0f} ms  {wtxt:<9} {flag}")
    return dict(backend=device, model=model_size, compute=compute, repeats=repeats,
                method=method, threads=n_threads, beam=beam,
                cold_start_s=round(cold, 2), rows=rows)


# ── Report ──────────────────────────────────────────────────────
def report(res):
    rows = res["rows"]
    print("\n" + "=" * 72)
    print(f"  Backend {res['backend']} · model {res['model']} ({res['compute']}) · "
          f"{res['repeats']} rep. · insertion « {res['method']} »")
    print("=" * 72)
    print(f"  Cold start: {res['cold_start_s']:.2f} s\n")

    # Latency + WER per length class
    print(f"  {'Class':<10}{'n':>3}{'P50':>9}{'P95':>9}{'perceived P50':>14}{'avg WER':>10}")
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
              f"{np.median(perc):>12.0f}ms{wtxt:>10}")

    # Filter control: false positives / false negatives
    print("\n  Filter control (false positive = real phrase suppressed = SERIOUS)")
    fp = fn = 0
    for r in rows:
        exp = r["p"]["expect"]
        if exp == "text" and r["suppressed"]:
            verdict = "❌ FALSE POSITIVE"; fp += 1
        elif exp == "filter" and not r["suppressed"]:
            verdict = "⚠️  false negative"; fn += 1
        else:
            verdict = "✓"
        print(f"    {verdict:<16} {r['p']['cat']:<22} -> {r['text'][:42]!r}")
    print(f"\n  Filter summary: {fp} false positive(s), {fn} false negative(s).")
    if fp:
        print("  ⚠️  At least one real phrase was filtered out: loosen the thresholds.")

    # Global aggregates (excluding silence)
    spoken = [r for r in rows if r["p"]["expect"] == "text"]
    all_lat = [x for r in spoken for x in r["lat_ms"]]
    wl = [r["wer"] for r in spoken if r["wer"] is not None]
    perc = [r["perceived_ms"] for r in spoken]

    out = os.path.join(DATA_DIR, f"result_{res['backend']}_{res['model']}.json")
    serial = dict(res); serial["rows"] = [
        dict(id=r["p"]["id"], cls=r["p"]["cls"], expect=r["p"]["expect"],
             text=r["text"], wer=r["wer"], suppressed=r["suppressed"],
             lat_ms=[round(x, 1) for x in r["lat_ms"]],
             perceived_ms=round(r["perceived_ms"], 1)) for r in rows]
    try:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(serial, f, indent=2, ensure_ascii=False)
        saved = out
    except Exception as e:
        saved = f"(JSON write failed: {e})"

    # ── Copyable summary (even without the JSON) ──
    print("\n" + "=" * 44)
    print("  LouLLabs Benchmark")
    print("=" * 44)
    print(f"  Model        : {res['model']}")
    print(f"  Backend      : {res['backend']}   Precision: {res['compute']}")
    print(f"  Repetitions  : {res['repeats']}")
    print(f"  Cold start   : {res['cold_start_s']:.1f} s")
    print(f"  Latency P50  : {np.median(all_lat):.0f} ms")
    print(f"  Latency P95  : {np.percentile(all_lat, 95):.0f} ms")
    print(f"  Perceived P50: {np.median(perc):.0f} ms  (inference + insertion « {res['method']} »)")
    print(f"  Average WER  : {np.mean(wl) * 100:.1f} %" if wl else "  Average WER  : -")
    print(f"  False rejects: {fp} / {len(spoken)}")
    print("=" * 44)
    print(f"  JSON: {saved}")
    print("=" * 44)
    print("  ↳ Copy-paste this block if you can't retrieve the JSON.")
    print("  Decision = best overall EXPERIENCE (perceived latency P50/P95 +")
    print("  WER + false rejects + stability + cold start), not « the fastest ».\n")


def main():
    ap = argparse.ArgumentParser(description="Benchmark LouLLabs STT")
    ap.add_argument("--record", action="store_true", help="(re)record the ENTIRE corpus")
    ap.add_argument("--run", action="store_true", help="measure without (re)recording")
    ap.add_argument("--backend", default="cpu", help="cpu | cuda | vulkan | rocm")
    ap.add_argument("--model", default="large-v3-turbo")
    ap.add_argument("--compute", default="int8")
    ap.add_argument("--repeats", type=int, default=3, help="repetitions for P50/P95")
    ap.add_argument("--insert", default="frappe", choices=["frappe", "collage"])
    ap.add_argument("--threads", type=int, default=0,
                    help="CPU cores (0 = all, default). Key lever on CPU.")
    ap.add_argument("--beam", type=int, default=3, help="beam size (1 = faster, 5 = more accurate)")
    args = ap.parse_args()

    print("=" * 44)
    print("  LouLLabs STT - Benchmark")
    print("=" * 44)

    if args.record:
        record_missing(force=True)
    elif not args.run:
        record_missing(force=False)   # record only what's missing

    corpus = load_corpus()
    if corpus is None:
        print("Incomplete corpus. Run first:  python tools/benchmark.py --record")
        sys.exit(1)
    print(f"Corpus: {len(corpus)} samples ready. Backend « {args.backend} ».")

    try:
        res = run_backend(args.backend, corpus, args.model, args.compute,
                          args.repeats, args.insert, args.threads, args.beam)
    except NotImplementedError as e:
        print(f"\n{e}\n(To be implemented in wave 2 - see the TODO in run_backend.)")
        sys.exit(2)
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted. The model may not have finished downloading.")
        print("   Rerun  python tools/benchmark.py --run  and let the bar finish.")
        sys.exit(130)
    except Exception as e:
        import traceback
        print("\n\n❌  The benchmark failed:", e)
        print("--- details ---")
        traceback.print_exc()
        print("\n↳ Copy-paste these last lines and I'll fix it.")
        sys.exit(3)
    report(res)


if __name__ == "__main__":
    main()
