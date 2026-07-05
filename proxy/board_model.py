# -*- coding: utf-8 -*-
"""Inference for the board-decoder model: predict the opponent's likely next boards.

Loads the trained decoder (proxy/model/board_decoder.pt + vocab.json) and, from the
opponent's identity/plan/board-history, beam-decodes the top-K boards they'll most
likely play next, each with a probability. This REPLACES the Oracle game-theoretic
opponent prediction (stage 1 of live_best_lines) with a behavioral prediction learned
from season-9 replays.

Perspective mapping (critical): the model was trained on a self-record SUBJECT and
predicts the SUBJECT's next board. At live inference the SUBJECT is the LIVE OPPONENT
we want to predict, so:
  cur_board (subject's own board)      -> the opponent's CURRENT board
  opp_board (board the subject faced)  -> MY last board (the opponent reacts to me)
  own history (own1/own2)              -> the opponent's older boards
  opp history (opp1/opp2)              -> MY older boards

Architecture + feature layout MUST match yixian replay analysis/train_decoder.py. If
torch or the checkpoint is unavailable, available() is False and callers fall back.

Card id encodes level: level = ((id//10000)%100)+1, base-line = id-((id//10000)%100)*10000.
"""
import json, os, threading

_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.environ.get("ORACLE_BOARD_MODEL", os.path.join(_HERE, "model"))
_CKPT = os.path.join(_MODEL_DIR, "board_decoder.pt")        # primary (CW=1.5: fidelity)
_CKPT2 = os.path.join(_MODEL_DIR, "board_decoder_cw4.pt")   # optional (CW=4: change-heavy)
_VOCAB = os.path.join(_MODEL_DIR, "vocab.json")

# ---- architecture constants (must match train_decoder.py v3) ----
(PAD, CHAR, SECT, CAREER, REALM, ROUND, SLOTS, FATE, DERIV, OPP, CUR, BOS, TGT, EOS_T,
 OWN1, OWN2, OPP1, OPP2, DAOXIN, OFATE, ODERIV) = range(21)
N_TYPES = 21
HPOS = {OWN1: 7, OWN2: 8, OPP1: 9, OPP2: 10}    # 7 scalars (0-6) then 4 history bags
HK = 8                      # cards pooled per history board
TGT_MAX = 9                 # full board <= 8 cards + EOS
N_COPIES = 4                # copies-seen bucket on CUR tokens (merge precursor)
DEFAULT_DAOXIN = 5800       # inference knob default: assume a strong opponent
_DIMS = dict(d=128, nhead=4, layers=2, ff=256)


def dx_bucket(dx):          # daoxin -> 0..9 (same mapping as training)
    return min(max((int(dx) - 3500) // 350, 0), 9)


def _line_of(cid):
    cid = int(cid or 0)
    return cid - ((cid // 10000) % 100) * 10000


def _level_of(cid):
    return ((int(cid or 0) // 10000) % 100) + 1


class BoardPredictor:
    def __init__(self):
        self.ok = False
        self._lock = threading.Lock()
        try:
            self._load()
            self.ok = True
        except Exception as e:
            self._err = str(e)

    # -- build the model + vocab from the checkpoint --
    def _load(self):
        import torch
        import torch.nn as nn
        self.torch = torch
        # Tiny model (~0.9M params): 2 threads is plenty and often FASTER than
        # all-cores (sync overhead), and it stops torch from bursting every core
        # during beam decode — the game we're assisting needs those cycles.
        try:
            torch.set_num_threads(2)
        except Exception:
            pass
        voc = json.load(open(_VOCAB, encoding="utf-8"))
        self.line2 = voc["line"]; self.fate2 = voc["fate"]; self.deriv2 = voc["deriv"]
        self.char2 = voc["char"]; self.career2 = voc["career"]
        n_line = len(self.line2); n_fate = len(self.fate2); n_deriv = len(self.deriv2)
        # scalar sub-spaces (sizes) packed with +1 pad offset — identical to training
        self.SCAL = [("char", len(self.char2) + 1), ("sect", 8),
                     ("career", len(self.career2) + 1), ("realm", 16),
                     ("round", 24), ("slots", 9), ("daoxin", 10)]
        off, self.SCAL_OFF, self.SCAL_SZ = 0, {}, dict(self.SCAL)
        for nm, sz in self.SCAL:
            self.SCAL_OFF[nm] = off; off += sz
        scal_total = off
        # v3: + faced-player fates(4) + derivations(4)
        self.CTX_MAX = 7 + 4 + 4 + 4 + 4 + 4 + 8 + 8
        self.T = self.CTX_MAX + 1 + TGT_MAX

        ck = torch.load(_CKPT, map_location="cpu", weights_only=False)
        self.CARD = {tuple(k) if isinstance(k, (list, tuple)) else k: v
                     for k, v in ck["CARD"].items()}
        C = ck["C"]; self.C = C; self.EOS = C; self.N_CLASS = C + 1
        # inverse maps: class -> (line-vocab-idx, level); line-vocab-idx -> line id
        self.cls2card = {cid: lv for lv, cid in self.CARD.items()}
        self.idx2line = {v: int(k) for k, v in self.line2.items()}
        self.meta = {k: ck.get(k) for k in
                     ("epoch", "jac", "merge_recall", "add_recall", "jac_late")}

        T, N_CLASS = self.T, self.N_CLASS
        d, nhead, layers, ff = (_DIMS[k] for k in ("d", "nhead", "layers", "ff"))

        class BoardDecoder(nn.Module):
            def __init__(s):
                super().__init__()
                s.type_emb = nn.Embedding(N_TYPES, d)
                s.card_emb = nn.Embedding(N_CLASS, d, padding_idx=0)
                s.scal_emb = nn.Embedding(scal_total + 1, d, padding_idx=0)
                s.fate_emb = nn.Embedding(n_fate + 1, d, padding_idx=0)
                s.deriv_emb = nn.Embedding(n_deriv + 1, d, padding_idx=0)
                s.cop_emb = nn.Embedding(N_COPIES, d, padding_idx=0)
                s.pos_emb = nn.Embedding(T, d)
                layer = nn.TransformerEncoderLayer(d, nhead, ff, 0.0, activation="gelu",
                                                   batch_first=True, norm_first=True)
                s.enc = nn.TransformerEncoder(layer, layers)
                s.ln = nn.LayerNorm(d); s.head = nn.Linear(d, N_CLASS)
                s.register_buffer("cmask", torch.triu(torch.ones(T, T, dtype=torch.bool), 1))
                s.register_buffer("pos_ids", torch.arange(T))

            def encode(s, typ, card, scal, fate, deriv, cop, hpool, pad):
                x = (s.type_emb(typ) + s.card_emb(card) + s.scal_emb(scal)
                     + s.fate_emb(fate) + s.deriv_emb(deriv) + s.cop_emb(cop)
                     + s.pos_emb(s.pos_ids))
                hp = s.card_emb(hpool)
                m = (hpool > 0).unsqueeze(-1).float()
                pooled = (hp * m).sum(2) / m.sum(2).clamp(min=1)
                x[:, 7:11, :] = x[:, 7:11, :] + pooled
                return s.ln(s.enc(x, mask=s.cmask, src_key_padding_mask=pad))

        self.model = BoardDecoder()
        self.model.load_state_dict(ck["model"])
        self.model.eval()
        # optional second model (CW=4, change-recall heavy) for portfolio diversity.
        # Same vocab/arch (trained on the same dataset); skipped if absent/mismatched.
        self.model2 = None
        try:
            ck2 = torch.load(_CKPT2, map_location="cpu", weights_only=False)
            if ck2.get("C") == C:
                m2 = BoardDecoder()
                m2.load_state_dict(ck2["model"]); m2.eval()
                self.model2 = m2
        except Exception:
            self.model2 = None

    # -- vocab lookups --
    def _card_class(self, cid):
        li = self.line2.get(str(_line_of(cid)), 0)
        return self.CARD.get((li, _level_of(cid)), 0)

    def _class_to_cardid(self, cls):
        lv = self.cls2card.get(cls)
        if not lv:
            return None
        li, level = lv
        base = self.idx2line.get(li)
        return None if base is None else base + (level - 1) * 10000

    # -- build the single-example input tensors (mirrors build_seq) --
    def _build(self, *, char, career, realm, rnd, sect, daoxin, cur_board, opp_board,
               fates, derivs, own_hist, opp_hist, faced_fates=None, faced_derivs=None):
        torch = self.torch
        T = self.T
        typ = [PAD] * T; card = [0] * T; scal = [0] * T; fate = [0] * T; deriv = [0] * T
        cop = [0] * T
        hpool = [[0] * HK for _ in range(4)]

        def sval(nm, raw):
            return 1 + self.SCAL_OFF[nm] + min(max(int(raw), 0), self.SCAL_SZ[nm] - 1)

        char_idx = self.char2.get(str(char), 0)
        career_idx = self.career2.get(str(career or 0), 0)
        for pos, (nm, raw, tp) in enumerate((
                ("char", char_idx, CHAR), ("sect", sect, SECT),
                ("career", career_idx, CAREER), ("realm", realm, REALM),
                ("round", rnd, ROUND), ("slots", max(1, min(rnd + 2, 8)), SLOTS),
                ("daoxin", dx_bucket(daoxin), DAOXIN))):
            typ[pos] = tp; scal[pos] = sval(nm, raw)
        # pooled history bag-tokens at 7..10: (own i-2, own i-3, opp i-2, opp i-3)
        hist_boards = [own_hist[0], own_hist[1], opp_hist[0], opp_hist[1]]
        for hk, (htype, hb) in enumerate(zip((OWN1, OWN2, OPP1, OPP2), hist_boards)):
            typ[HPOS[htype]] = htype
            for cpos, cid in enumerate([c for c in (hb or []) if c][:HK]):
                hpool[hk][cpos] = self._card_class(cid)
        t = 11
        for f in [x for x in (fates or []) if x][:4]:
            typ[t] = FATE; fate[t] = self.fate2.get(str(f), 0); t += 1
        for dd in [x for x in (derivs or []) if x][:4]:
            typ[t] = DERIV; deriv[t] = self.deriv2.get(str(dd), 0); t += 1
        # v3: the FACED player's fates/derivations — at live inference that's US,
        # always known from the wire (the subject reacts to our plan).
        for f in [x for x in (faced_fates or []) if x][:4]:
            typ[t] = OFATE; fate[t] = self.fate2.get(str(f), 0); t += 1
        for dd in [x for x in (faced_derivs or []) if x][:4]:
            typ[t] = ODERIV; deriv[t] = self.deriv2.get(str(dd), 0); t += 1
        for cid in [c for c in (opp_board or []) if c][:8]:
            typ[t] = OPP; card[t] = self._card_class(cid); t += 1
        cur_lines = set()
        cur_ids8 = [c for c in (cur_board or []) if c][:8]
        line_cnt = {}
        for cid in cur_ids8:
            line_cnt[_line_of(cid)] = line_cnt.get(_line_of(cid), 0) + 1
        for cid in cur_ids8:
            typ[t] = CUR; card[t] = self._card_class(cid); cur_lines.add(_line_of(cid))
            cop[t] = min(line_cnt[_line_of(cid)], N_COPIES - 1)   # duplicates -> merges
            t += 1
        bos = t; typ[t] = BOS
        pad = [x == PAD for x in typ]
        pad[0] = False
        for p in range(7, 11):
            pad[p] = False
        L = lambda a: torch.tensor([a])
        return dict(typ=L(typ), card=L(card), scal=L(scal), fate=L(fate),
                    deriv=L(deriv), cop=L(cop),
                    hpool=torch.tensor([hpool]), pad=L(pad)), bos, cur_lines

    def _beam_boards(self, model, base, bos, slots, width=16, slot_fill=True):
        """beam decode with `model` -> [(class-tuple, logp)] best-first. slot_fill=True
        forces exactly `slots` cards (fill the board); slot_fill=False lets the model
        END the board early via EOS (natural length — real boards leave a slot empty
        ~14% of the time, so the opponent prediction should be allowed to under-fill)."""
        torch = self.torch
        beams = [(base["typ"][0].tolist(), base["card"][0].tolist(), bos, 0.0, [])]
        done = []
        for _ in range(slots):
            if not beams:
                break
            B = len(beams)
            typ = torch.tensor([b[0] for b in beams])
            card = torch.tensor([b[1] for b in beams])
            pad = torch.tensor([[x == PAD for x in b[0]] for b in beams])
            pad[:, 0] = False; pad[:, 7:11] = False
            h = model.encode(typ, card, base["scal"].expand(B, -1),
                             base["fate"].expand(B, -1), base["deriv"].expand(B, -1),
                             base["cop"].expand(B, -1),
                             base["hpool"].expand(B, -1, -1), pad)
            pos = torch.tensor([b[2] for b in beams])
            row = torch.log_softmax(model.head(h[torch.arange(B), pos]), -1)
            row[:, 0] = -1e9                            # never emit PAD
            if slot_fill:
                row[:, self.EOS] = -1e9                 # never stop early
            nxt = []
            for bi, bm in enumerate(beams):
                t = bm[2]
                if not slot_fill and len(bm[4]) >= 1:   # model chooses to END the board
                    done.append((bm[4], bm[3] + float(row[bi][self.EOS])))
                if t + 1 >= self.T:
                    done.append((bm[4], bm[3])); continue
                for c in torch.topk(row[bi], 8).indices.tolist():
                    if c == self.EOS or self._class_to_cardid(c) is None:
                        continue
                    ntyp = list(bm[0]); ncard = list(bm[1])
                    ntyp[t + 1] = TGT; ncard[t + 1] = c
                    nxt.append((ntyp, ncard, t + 1, bm[3] + float(row[bi][c]), bm[4] + [c]))
            nxt.sort(key=lambda x: -x[3])
            beams = nxt[:width]
        for bm in beams:                                # reached `slots` (full board)
            done.append((bm[4], bm[3]))
        seen = {}
        for cls, lp in done:
            k = tuple(cls)
            if k not in seen or lp > seen[k]:
                seen[k] = lp
        return sorted(seen.items(), key=lambda kv: -kv[1])

    def _diverse_ids(self, boards, k):
        """best board per line-SET (diversity), as card-id lists; up to k."""
        out, seen = [], set()
        for cls, _ in boards:
            ids = [x for x in (self._class_to_cardid(c) for c in cls) if x is not None]
            s = frozenset(_line_of(c) for c in ids)
            if not ids or s in seen:
                continue
            seen.add(s); out.append(ids)
            if len(out) >= k:
                break
        return out

    def predict(self, *, char, career, realm, rnd, cur_board, opp_board=None,
                fates=None, derivs=None, faced_fates=None, faced_derivs=None,
                own_hist=(None, None), opp_hist=(None, None),
                daoxin=DEFAULT_DAOXIN, top_k=20, beam=32, cover=0.92):
        """The opponent's likely next boards weighted by the MODEL's own confidence:
        [(card_ids, prob)]. A WIDE beam yields many distinct boards; each board's
        probability is the softmax of its sequence log-prob — so a CONFIDENT model
        concentrates the mass on a few lines and an UNSURE one spreads it across many.
        Adaptive nucleus: keep the most-likely boards until they cover `cover` of the
        mass (capped at top_k), so the NUMBER of lines self-adjusts to confidence
        (few when there's really one line, many when it's open). The CW=4 (change-heavy)
        model's boards are folded in, slightly down-weighted, for extra diversity; the
        carry-over board is always a candidate. Deterministic."""
        if not self.ok:
            return None
        import math
        torch = self.torch
        sect = int((char or 0) // 1000000)
        slots = max(1, min(int(rnd) + 2, 8))
        cur_ids = [int(c) for c in (cur_board or []) if c]
        with self._lock, torch.no_grad():
            base, bos, _cur = self._build(
                char=char, career=career, realm=realm, rnd=rnd, sect=sect, daoxin=daoxin,
                cur_board=cur_ids, opp_board=opp_board,
                fates=fates, derivs=derivs, own_hist=own_hist, opp_hist=opp_hist,
                faced_fates=faced_fates, faced_derivs=faced_derivs)
            b1 = self._beam_boards(self.model, base, bos, slots, width=beam)
            b2 = self._beam_boards(self.model2, base, bos, slots, width=beam) \
                if self.model2 is not None else []
        # distinct ORDERED boards -> best sequence log-prob (blend both; CW4 down-weighted)
        logp = {}
        def fold(boards, bias):
            for cls, lp in boards:
                ids = tuple(x for x in (self._class_to_cardid(c) for c in cls) if x is not None)
                if ids and (ids not in logp or lp + bias > logp[ids]):
                    logp[ids] = lp + bias
        fold(b1, 0.0)
        fold(b2, -1.0)
        if cur_ids and tuple(cur_ids) not in logp:      # persistence always in play
            logp[tuple(cur_ids)] = (max(logp.values()) - 3.0) if logp else 0.0
        if not logp:
            return None
        mx = max(logp.values())
        # Softmax, then GROUP orderings by card MULTISET (sorted ids). The 20 lines must be
        # distinct card-SETS for coverage — otherwise the beam returns near-duplicate
        # orderings of one set and the extra lines add nothing. Combat cares about the
        # cards+levels; order is optimized separately in the best-response. Representative =
        # the highest-probability ordering; its set's prob is the sum over orderings.
        grp = {}
        for ids, lp in sorted(logp.items(), key=lambda kv: -kv[1]):
            key = tuple(sorted(ids))
            if key not in grp:
                grp[key] = [0.0, list(ids)]             # first seen = most likely ordering
            grp[key][0] += math.exp(lp - mx)
        Z = sum(v[0] for v in grp.values()) or 1.0
        # adaptive nucleus: most-likely SETS until they cover `cover` of the mass
        out, cum = [], 0.0
        for e, board in sorted(grp.values(), key=lambda v: -v[0]):
            p = e / Z
            out.append((board, p)); cum += p
            if len(out) >= top_k or cum >= cover:
                break
        s = sum(p for _, p in out) or 1.0
        return [(b, p / s) for b, p in out] or None

    def generate_board(self, *, char, career, realm, rnd, cur_board, opp_board=None,
                       fates=None, derivs=None, own_hist=(None, None), opp_hist=(None, None),
                       available, daoxin=DEFAULT_DAOXIN, top_k=6, beam=16):
        """Generate MY next board(s) with the model, CONSTRAINED to `available` (a list
        of card ids I actually hold). At each step the model's choice is masked to cards
        still available (copy counts respected); if its top pick isn't available it falls
        to the next. Cards not in the model vocab are dropped. Returns [(board_ids, prob)]
        ordered by likelihood — sensible learned boards built only from my real cards."""
        if not self.ok:
            return None
        import math
        from collections import Counter
        torch = self.torch
        sect = int((char or 0) // 1000000)
        slots = max(1, min(int(rnd) + 2, 8))
        avail = Counter()                          # available card CLASSES with counts
        for cid in (available or []):
            c = self._card_class(int(cid))
            if c:
                avail[c] += 1
        if not avail:
            return None
        maxlen = min(slots, sum(avail.values()))
        with self._lock, torch.no_grad():
            base, bos, _ = self._build(
                char=char, career=career, realm=realm, rnd=rnd, sect=sect, daoxin=daoxin,
                cur_board=[int(c) for c in (cur_board or []) if c], opp_board=opp_board,
                fates=fates, derivs=derivs, own_hist=own_hist, opp_hist=opp_hist)
            beams = [(base["typ"][0].tolist(), base["card"][0].tolist(), bos, 0.0, [])]
            for _ in range(maxlen):
                B = len(beams)
                typ = torch.tensor([b[0] for b in beams]); card = torch.tensor([b[1] for b in beams])
                pad = torch.tensor([[x == PAD for x in b[0]] for b in beams])
                pad[:, 0] = False; pad[:, 7:11] = False
                h = self.model.encode(typ, card, base["scal"].expand(B, -1),
                                      base["fate"].expand(B, -1), base["deriv"].expand(B, -1),
                                      base["cop"].expand(B, -1),
                                      base["hpool"].expand(B, -1, -1), pad)
                pos = torch.tensor([b[2] for b in beams])
                logp = torch.log_softmax(self.model.head(h[torch.arange(B), pos]), -1)
                nxt = []
                for bi, bm in enumerate(beams):
                    t = bm[2]
                    placed = Counter(bm[4])
                    allowed = [c for c in avail if avail[c] - placed[c] > 0]   # copies left
                    if t + 1 >= self.T or not allowed:
                        nxt.append(bm); continue
                    row = logp[bi]
                    allowed.sort(key=lambda c: -float(row[c]))     # model preference order
                    for c in allowed[:6]:
                        ntyp = list(bm[0]); ncard = list(bm[1]); ntyp[t + 1] = TGT; ncard[t + 1] = c
                        nxt.append((ntyp, ncard, t + 1, bm[3] + float(row[c]), bm[4] + [c]))
                nxt.sort(key=lambda x: -x[3]); beams = nxt[:beam]
            out = {}
            for bm in beams:
                ids = tuple(x for x in (self._class_to_cardid(c) for c in bm[4]) if x is not None)
                if ids and (ids not in out or bm[3] > out[ids]):
                    out[ids] = bm[3]
            items = sorted(out.items(), key=lambda kv: -kv[1])[:top_k]
            mx = items[0][1] if items else 0.0
            probs = [math.exp(lp - mx) for _, lp in items]; s = sum(probs) or 1.0
            return [(list(b), p / s) for (b, _), p in zip(items, probs)]


_predictor = None
_predictor_lock = threading.Lock()


def get_predictor():
    """lazy singleton; returns a loaded BoardPredictor or one whose .ok is False."""
    global _predictor
    if _predictor is None:
        with _predictor_lock:
            if _predictor is None:
                _predictor = BoardPredictor()
    return _predictor


def available():
    return get_predictor().ok
