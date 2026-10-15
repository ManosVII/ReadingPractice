"""
Extract the reading passages (stories, poems, dialogues, letters, informational
texts) from the Greek primary-school language textbooks (Γλώσσα Α΄–ΣΤ΄
Δημοτικού, Βιβλίο Μαθητή) into the `texts` table.

The extractor works on lessons, not on single PDF blocks:

  * Every page is turned into visual line segments (spans on one baseline,
    split at wide gaps) and put in reading order with a recursive XY-cut,
    so columns are read one after the other.
  * Running headers/footers and page numbers are found by their repeated
    position and text across pages, not by a phrase list.
  * A passage STARTS at a lesson title (the title typography of the book,
    reassembled from fragments when the title is curved; for books whose
    titles are drawings, the title comes from the table of contents).
  * A passage ENDS at its attribution line (smaller type, set off from the
    text), at a section heading, at a numbered exercise item, or at the
    next title, whichever comes first. It may run over columns and pages.
  * Paragraphs are kept (one per line), poems keep their verse lines and
    stanzas (blank line between stanzas), hyphenated words are re-joined.
  * Anything that is not clearly a passage goes to data/review_uncertain.json.

Usage:
    python extract_pdfs.py                       # all books -> data/reading_new.db
    python extract_pdfs.py --publish             # ...then copy the texts into data/reading.db
    python extract_pdfs.py --only g_dimotikou_b  # one book
    python extract_pdfs.py --debug g_dimotikou_b:21   # show segments of a page
Options:
    --pdf-dir DIR   folder with the PDFs (default: pdfs/ next to this file);
                    a missing PDF is downloaded into it once, if a URL is known
    --db FILE       target database (default: data/reading_new.db)
"""
import argparse
import json
import re
import sqlite3
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).parent))

import fitz  # PyMuPDF

ROOT = Path(__file__).parent
DEFAULT_PDF_DIR = ROOT / "pdfs"
DEFAULT_DB = ROOT / "data" / "reading_new.db"
REVIEW_FILE = ROOT / "data" / "review_uncertain.json"
PROTECTED_DB = ROOT / "data" / "reading.db"

EBOOKS = "https://ebooks.edu.gr/ebooks/v/pdf/8547"

# ── Typography profiles ──────────────────────────────────────────────────────
# Each series of books has its own typography. Font specs are
# (font-name prefix, min size, max size). They were checked on every book of
# the series (see the report). Everything else is derived from layout.
#   title        lesson/text titles; a passage may end without attribution
#   weak_title   ambiguous title typography; the passage needs an attribution
#   heading      exercise section headings; they end a passage
#   keep_lines   early-literacy books: keep every printed line
#   single_page  a passage does not continue to the next page
#   toc_titles   titles that are drawings are taken from the table of contents
#   need_attribution  a passage is only accepted when it ends at its source line
#   unit_title   unit name on the unit's opening page (for chapter labels)
#   lesson_opener  lesson name on the lesson's opening page, matched to the contents
SERIES = {
    "A1": dict(title=[("CFBaby", 23.5, 29)], body_min=15.0, keep_lines=True, single_page=True, min_words=6),
    "A2": dict(title=[("CFBaby", 20.5, 23.5)], body_min=15.0, keep_lines=True, single_page=True, min_words=6),
    "B": dict(title=[("CFBaby", 17.5, 18.5)], need_attribution=True,
              lesson_opener=[("CFBaby", 23.5, 25)]),
    "G": dict(title=[("PFCatalog-Bold", 19.5, 30)],
              heading=[("CFNote-Bold", 18, 25), ("CF-Note-Bold", 18, 25), ("CFBaby-Bd", 15, 17)],
              toc_titles=True, need_attribution=True),
    "D": dict(title=[("StoneSansITCHel-Bold", 18.5, 20.5)], need_attribution=True,
              unit_title=[("CF-Stamp-Bold", 26, 32)]),
    "E": dict(title=[("CFSmooth-ExtraBold", 17, 26)],
              weak_title=[("TriplexSansOTGR-Bold", 16, 19)],
              heading=[("CFMarker-Bold", 26, 32)], need_attribution=True),
    "ST": dict(title=[("PFCatalog-Regular", 18.5, 24.5)],
               weak_title=[("PFCatalog-Bold", 17, 19)],
               heading=[("CFMarker-Bold", 26, 32)], need_attribution=True),
}

BOOKS = [
    # source_id, label, series, file name in the PDF folder, download URL (None if unknown)
    ("a_dimotikou", "Γλώσσα Α' Δημοτικού — Τεύχος Α", "A1",
     "10-0002-02_V3_Glossa_A-Dimotikou_Vivlio-Mathiti_Teuchos-A.pdf",
     f"{EBOOKS}/459/10-0002-02_V3_Glossa_A-Dimotikou_Vivlio-Mathiti_Teuchos-A/"),
    ("a_dimotikou_b", "Γλώσσα Α' Δημοτικού — Τεύχος Β", "A2",
     "10-0004-02_V2_Glossa_A-Dimotikou_Vivlio-Mathiti_Teuchos-B.pdf",
     f"{EBOOKS}/462/10-0004-02_V2_Glossa_A-Dimotikou_Vivlio-Mathiti_Teuchos-B/"),
    ("b_dimotikou", "Γλώσσα Β' Δημοτικού — Τεύχος Α", "B",
     "10-0030-02_Glossa_B-Dimotikou_Vivlio-Mathiti_Teuchos-A.pdf",
     f"{EBOOKS}/499/10-0030-02_Glossa_B-Dimotikou_Vivlio-Mathiti_Teuchos-A/"),
    ("b_dimotikou_b", "Γλώσσα Β' Δημοτικού — Τεύχος Β", "B",
     "10-0032-02_Glossa_B-Dimotikou_Vivlio-Mathiti_Teuchos-B.pdf",
     f"{EBOOKS}/502/10-0032-02_Glossa_B-Dimotikou_Vivlio-Mathiti_Teuchos-B/"),
    ("b_dimotikou_g", "Γλώσσα Β' Δημοτικού — Τεύχος Γ", "B",
     "10-0034-02-Glossa_B-Dimotikou_Vivlio-Mathiti_Teuchos-G.pdf",
     f"{EBOOKS}/504/10-0034-02-Glossa_B-Dimotikou_Vivlio-Mathiti_Teuchos-G/"),
    ("g_dimotikou", "Γλώσσα Γ' Δημοτικού — Τεύχος Α", "G",
     "10-0048-02_Glossa_G-Dimotikou_Vivlio-Mathiti_Teuchos-A.pdf",
     f"{EBOOKS}/528/10-0048-02_Glossa_G-Dimotikou_Vivlio-Mathiti_Teuchos-A/"),
    ("g_dimotikou_b", "Γλώσσα Γ' Δημοτικού — Τεύχος Β", "G",
     "10-0050-02_V2_Glossa_G-Dimotikou_Vivlio-Mathiti_Teuchos-B.pdf",
     f"{EBOOKS}/531/10-0050-02_V2_Glossa_G-Dimotikou_Vivlio-Mathiti_Teuchos-B/"),
    ("g_dimotikou_g", "Γλώσσα Γ' Δημοτικού — Τεύχος Γ", "G",
     "10-0052-02_Glossa_G-Dimotikou_Vivlio-Mathiti_Teuchos-G.pdf",
     f"{EBOOKS}/533/10-0052-02_Glossa_G-Dimotikou_Vivlio-Mathiti_Teuchos-G/"),
    ("d_dimotikou", "Γλώσσα Δ' Δημοτικού — Τεύχος Α", "D",
     "10-0202-01_V3_Glossa_D-Dimotikou_Vivlio-Mathiti_Teuchos-A.pdf",
     f"{EBOOKS}/709/10-0202-01_V3_Glossa_D-Dimotikou_Vivlio-Mathiti_Teuchos-A/"),
    ("d_dimotikou_b", "Γλώσσα Δ' Δημοτικού — Τεύχος Β", "D",
     "10-0084-02_V2_Glossa_D-Dimotikou_Vivlio-Mathiti_Teuchos-B.pdf",
     f"{EBOOKS}/578/10-0084-02_V2_Glossa_D-Dimotikou_Vivlio-Mathiti_Teuchos-B/"),
    ("d_dimotikou_g", "Γλώσσα Δ' Δημοτικού — Τεύχος Γ", "D",
     "10-0086-02_V3_Glossa_D-Dimotikou_Vivlio-Mathiti_Teuchos-G.pdf",
     f"{EBOOKS}/580/10-0086-02_V3_Glossa_D-Dimotikou_Vivlio-Mathiti_Teuchos-G/"),
    ("e_dimotikou", "Γλώσσα Ε' Δημοτικού — Τεύχος Α", "E",
     "10-0245-01_V1_Glossa_E-Dimotikou_Vivlio-Mathiti_Teuchos-A.pdf",
     f"{EBOOKS}/611/10-0245-01_V1_Glossa_E-Dimotikou_Vivlio-Mathiti_Teuchos-A/"),
    ("e_dimotikou_b", "Γλώσσα Ε' Δημοτικού — Τεύχος Β", "E",
     "10-0112-02_V2_Glossa_E-Dimotikou_Vivlio-Mathiti_Teuchos-B.pdf",
     f"{EBOOKS}/614/10-0112-02_V2_Glossa_E-Dimotikou_Vivlio-Mathiti_Teuchos-B/"),
    ("e_dimotikou_g", "Γλώσσα Ε' Δημοτικού — Τεύχος Γ", "E",
     "10-0114-02_V2_Glossa_E-Dimotikou_Vivlio-Mathiti_Teuchos-G.pdf",
     f"{EBOOKS}/616/10-0114-02_V2_Glossa_E-Dimotikou_Vivlio-Mathiti_Teuchos-G/"),
    ("st_dimotikou", "Γλώσσα ΣΤ' Δημοτικού — Τεύχος Α", "ST",
     "10-0156-02_V3_Glossa_ST-Dimotikou_Vivlio-Mathiti_Teuchos-A.pdf", None),
    ("st_dimotikou_b", "Γλώσσα ΣΤ' Δημοτικού — Τεύχος Β", "ST",
     "10-0158-02_Glossa_ST-Dimotikou_Vivlio-Mathiti_Teuchos-B.pdf", None),
    ("st_dimotikou_g", "Γλώσσα ΣΤ' Δημοτικού — Τεύχος Γ", "ST",
     "10-0160-02_V2_Glossa_ST-Dimotikou_Vivlio-Mathiti_Teuchos-G.pdf", None),
]

# Secondary signal only: a paragraph that starts with one of these imperative
# exercise verbs ends a passage, and a block that starts with one is never a
# passage. Primary signals are layout (headings, numbering, attribution).
EXERCISE_VERBS = (
    "διάβασε διαβάστε ξαναδιάβασε γράψε γράψτε βρες βρείτε απάντησε απαντήστε "
    "συζήτησε συζητήστε συμπλήρωσε συμπληρώστε υπογράμμισε υπογραμμίστε κύκλωσε "
    "κυκλώστε αντίγραψε αντιγράψτε ζωγράφισε ζωγραφίστε σχεδίασε σχεδιάστε "
    "αντιστοίχισε αντιστοιχίστε παρατήρησε παρατηρήστε ταίριαξε ταιριάξτε "
    "αρίθμησε αριθμήστε χρωμάτισε χρωματίστε μάθε μάθετε φτιάξε φτιάξτε "
    "ψάξε ψάξτε διάλεξε διαλέξτε σύγκρινε συγκρίνετε περιγράψτε περίγραψε "
    "βάλτε δείτε κάντε σημείωσε σημειώστε εξήγησε εξηγήστε ετοιμάστε ονόμασε ονομάστε "
    "χωριστείτε ρωτήστε παίξτε ακούστε δείξτε ακολούθησε ακολουθήστε"
).split()

# Words that mark a bibliographic attribution (secondary signal).
ATTRIBUTION_CUES = re.compile(
    r"εκδ\.|εκδόσεις|μετάφρ|μτφρ|διασκευ|στίχοι|μουσική:|τραγούδι|εφημερίδα|"
    r"περιοδικ|ανθολόγιο|απόσπασμα|αποσπάσματα|συγγραφικής|ανέκδοτο|\b1[89]\d\d\b|\b20[0-2]\d\b",
    re.IGNORECASE)

# Titled texts without a source line that were checked by eye against the
# printed page. Each entry gives the words the passage ends with; the text is
# cut right after them (nothing is rewritten) and every other check still
# applies. If the words are not found, the text stays in the review file.
REVIEWED_PASSAGES = {
    ("b_dimotikou", "Το σαλιγκάρι"): "το ’πιασε μεγάλο κέφι!",
    ("b_dimotikou", "Ο Αρμπέν χάνει το δόντι του"): "να τρώω παξιμάδια».",
    ("b_dimotikou_b", "Τα γενέθλια της Χαράς"): "Στις 9.20 όλοι είχαν φύγει.",
    ("b_dimotikou_b", "Μαζί είναι καλύτερα"): "τη φιλία τους.",
    ("b_dimotikou_g", "Τα παιδιά στην πόλη"): "και δουλειά και σκόλη!",
    ("b_dimotikou_g", "Τα ψηλά βουνά"): "αξέχαστο καλοκαίρι.",
    ("b_dimotikou_g", "Νεαροί μαθητές αναλαμβάνουν δράση!"): "ΣΚOΥΠΙΔOΤOΠO».",
    ("b_dimotikou_g", "Άνοιξη στο Παγγαίο"): "συμμετείχαν στη γιορτή.",
    ("b_dimotikou_g", "Το ουράνιο τόξο"): "διώχνοντας τα σύννεφα μακριά μου.",
    ("b_dimotikou_g", "Ο λύκος"): "γίνονται καλοί φίλοι τους.",
    ("b_dimotikou_g", "Η χελώνα καρέτα καρέτα"): "τα άλλα ζώα ή τον άνθρωπο.",
    ("g_dimotikou", "Το τετράδιο ζωγραφικής"): "λυπάται που τη βλέπει τώρα έτσι.",
    ("g_dimotikou_g", "Το πιο γλυκό ψωμί"): "εκεί που του ’λεγε.",
    ("d_dimotikou", "Στάση βροχοσταλίδων"): "θα μας πουν τι φταίει.",
    ("d_dimotikou_b", "Μαγειρεύουμε με ελαιόλαδο"): "στις σαλάτες και στα λαχανικά.",
    ("e_dimotikou", "Η πολιτιστική ζωή της Θεσσαλονίκης"): "πολύχρωμο παρελθόν της.",
    ("e_dimotikou", "Οι φίλοι τραγουδάνε"): "χωρίς να το κατένε.",
    ("e_dimotikou_b", "Όταν η Βιβλιοθήκη συναντά τους αναγνώστες"): "γενικού ενδιαφέροντος κτλ.",
    ("e_dimotikou_b", "Όνειρα για ταξίδια στ’ αστέρια"): "αλλά το «πότε».",
    ("st_dimotikou_b", "Από τον χαλκό στο γυαλί"): "χιλιάδες κλήσεις ταυτόχρονα.",
    ("st_dimotikou_g", "Μεγάλη Πέμπτη Σήμερον κρεμάται επί ξύλου"): "την ένδοξη Ανάστασή σου.",
}


# Texts checked by eye and found wrong in a way the rules cannot detect.
# They always go to the review file.
REVIEWED_REJECT = {
    ("b_dimotikou_g", "Μακαρόνια"): "two-column poem read row by row (stanzas in the wrong order)",
    ("d_dimotikou_b", "Παιχνίδια με τις λέξεις"): "first row of the two columns interleaved, and the couplet "
                                                  "that is also the unit's name was removed as a running header",
}


def _reviewed_reject(source_id, title):
    want = _norm_running(title.translate(_LATIN_LOOKALIKE))
    for (sid, t), why in REVIEWED_REJECT.items():
        if sid == source_id and _norm_running(t.translate(_LATIN_LOOKALIKE)) == want:
            return why
    return None


def _reviewed_end(source_id, title):
    want = _norm_running(title.translate(_LATIN_LOOKALIKE))
    for (sid, t), end in REVIEWED_PASSAGES.items():
        if sid == source_id and _norm_running(t.translate(_LATIN_LOOKALIKE)) == want:
            return end
    return None


TERMINAL = tuple(".!;;…»\"”·")
HYPHENS = "-­‐‑"
DASH_START = re.compile(r"^[—–―\-]\s")
SPEAKER = re.compile(r"^[A-ZΑ-ΩΆ-Ώ][^\s:]{1,15}:\s")
NUMBERED = re.compile(r"^\(?\d{1,2}\s*[.)]?\s+\S|^\(?\d{1,2}[.)]\S")
FILL_IN = re.compile(r"\.{6,}|_{3,}|…{3,}|(?:_\s){2,}|(?:\.\s){5,}")
DOTS_ONLY = re.compile(r"^[.\s…]{6,}$")
LIST_LINE = re.compile(r"^\s*(?:[•●■▪◦-]|[lw]\s|[-–]\s*\S+\s*$)")
TABLE_LINE = re.compile(r"^[^\W\d_][^:.!;]{0,25}:\s*\S")


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def greek_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿") / len(letters)


_LATIN_LOOKALIKE = str.maketrans("ABEZHIKMNOPTYXaeiko", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧαεικο")


def first_word(text: str) -> str:
    m = re.match(r"[\W\d_]*([^\W\d_]+)", text.translate(_LATIN_LOOKALIKE))
    return strip_accents(m.group(1).lower()) if m else ""


_VERBS = {strip_accents(v) for v in EXERCISE_VERBS}


def starts_with_exercise_verb(text: str) -> bool:
    if re.match(r"\s*[—–―\-«\"“(]", text):   # dialogue or quotation, not an instruction
        return False
    return first_word(text) in _VERBS


def font_match(seg, specs) -> bool:
    return any(seg.font.startswith(f) and lo <= seg.size <= hi for f, lo, hi in specs or [])


# ── Page model ───────────────────────────────────────────────────────────────

@dataclass
class Seg:
    page: int                 # 1-based PDF page
    x0: float
    y0: float
    x1: float
    y1: float
    text: str
    size: float
    font: str
    bold: bool
    frag: bool = False        # rotated fragment of a curved title
    raw: str = ""             # unstripped text (fragments keep their spaces)
    kind: str = ""            # running/title/weak_title/heading/exercise/small/body/decor
    col: tuple = ()           # column path from the XY-cut
    order: int = 0

    @property
    def w(self):
        return self.x1 - self.x0


def _span_text(chars):
    """Span text from its glyphs. A space that the next glyph overprints is
    not visible on the page (the PDFs contain such spaces inside words,
    e.g. 'πο λύ' printed as 'πολύ'), so it is left out."""
    out = []
    for i, c in enumerate(chars):
        size = max(c["bbox"][3] - c["bbox"][1], 1)
        if c["c"] == " " and i + 1 < len(chars):
            if chars[i + 1]["origin"][0] - c["origin"][0] < 0.08 * size:   # zero advance
                continue
        if i and not c["c"].isspace() and not chars[i - 1]["c"].isspace() \
                and c["bbox"][0] - chars[i - 1]["bbox"][2] > 0.3 * size:
            out.append(" ")             # visible gap without a space glyph (tab stop)
        out.append(c["c"])
    return "".join(out)


def _span_records(page):
    """Horizontal-ish spans of the page as dicts; vertical text is dropped."""
    out = []
    for b in page.get_text("rawdict")["blocks"]:
        if b.get("type") != 0:
            continue
        for line in b["lines"]:
            dx, dy = line["dir"]
            if abs(dy) > 0.35 or dx <= 0:
                continue
            rotated = abs(dy) > 0.02
            space_before = False
            for s in line["spans"]:
                text = _span_text(s["chars"])
                if not text.strip():
                    space_before = bool(text)     # a span that is only a space still separates words
                    continue
                if space_before and not text[0].isspace():
                    text = " " + text
                space_before = False
                trail = s["chars"][-1]["origin"][0] if text.endswith(" ") else None
                out.append(dict(text=text, bbox=s["bbox"], size=s["size"], font=s["font"],
                                bold=bool(s["flags"] & 16) or "Bold" in s["font"],
                                base=s["origin"][1], rotated=rotated, trail=trail,
                                first=s["chars"][0]["origin"][0]))
    return out


def _make_seg(pno, spans):
    spans = sorted(spans, key=lambda s: s["bbox"][0])
    parts = []
    for i, s in enumerate(spans):
        if i:
            prev = spans[i - 1]
            gap = s["bbox"][0] - prev["bbox"][2]
            if prev.get("trail") is not None and s["first"] - prev["trail"] < 0.08 * s["size"] \
                    and parts and parts[-1].endswith(" "):
                parts[-1] = parts[-1][:-1]      # trailing space overprinted by the next span
            elif gap > 0.25 * s["size"] and not prev["text"][-1:].isspace() and not s["text"][:1].isspace():
                parts.append(" ")
        t = s["text"]
        if i and t.startswith(" ") and s.get("first") is not None and s["first"] < spans[i - 1]["bbox"][2] - 0.5:
            t = t[1:]                    # leading space printed over the previous glyph: not visible
        parts.append(t)
    text = re.sub(r"[ \t ]+", " ", "".join(parts)).strip()
    weight = Counter()
    for s in spans:
        weight[(round(s["size"], 1), s["font"], s["bold"])] += len(s["text"].strip())
    (size, font, bold), _ = weight.most_common(1)[0]
    return Seg(pno, min(s["bbox"][0] for s in spans), min(s["bbox"][1] for s in spans),
               max(s["bbox"][2] for s in spans), max(s["bbox"][3] for s in spans),
               text, size, font, bold, raw="".join(parts))


def page_segments(page, pno):
    """Visual line segments: spans on one baseline, split at wide gaps."""
    recs = _span_records(page)
    segs = []
    flat = [r for r in recs if not r["rotated"]]
    for r in recs:
        if r["rotated"]:
            seg = _make_seg(pno, [r])
            seg.frag = True
            segs.append(seg)
    flat.sort(key=lambda r: (r["base"], r["bbox"][0]))
    rows = []
    def same_line(r, m):
        lo, hi = sorted((r["size"], m["size"]))
        if hi > 1.6 * lo:                # very different type sizes never share a line
            return False
        if hi > 1.15 * lo and r["font"][:6] != m["font"][:6]:
            return False                 # another typeface of another size: a tab, not this line
        return abs(r["base"] - m["base"]) <= 0.35 * lo

    for r in flat:
        for row in rows:
            if any(same_line(r, m) for m in row):
                row.append(r)
                break
        else:
            rows.append([r])
    def gutter(a, b, size, y0, y1, fonts=(), need_sides=False):
        """True when no text of nearby lines (in the same typeface) crosses the gap between a and b.
        With need_sides, nearby lines must also have text on both sides of the gap
        (a real column channel, not a word gap inside a short verse line)."""
        mid = (a + b) / 2
        left = right = False
        for o in flat:
            if fonts and o["font"] not in fonts:
                continue                 # hidden tabs and headers in other faces do not count
            if o["bbox"][3] < y0 - 2.5 * size or o["bbox"][1] > y1 + 2.5 * size:
                continue
            if not 0.88 * size <= o["size"] <= 1.12 * size:
                continue                 # titles and captions do not count as text lines
            if o["bbox"][0] < mid - 1 < mid + 1 < o["bbox"][2]:
                return False
            if not (o["bbox"][1] < y1 and y0 < o["bbox"][3]):      # another line, not this one
                left |= o["bbox"][2] <= mid
                right |= o["bbox"][0] >= mid
        return not need_sides or (left and right)

    for row in rows:
        row.sort(key=lambda r: r["bbox"][0])
        cur = [row[0]]
        for r in row[1:]:
            size = max(r["size"], cur[-1]["size"])
            end = max(c["bbox"][2] for c in cur)
            gap = r["bbox"][0] - end
            left_text = "".join(c["text"] for c in cur).rstrip()
            split = gap > max(1.8 * size, 18)
            if left_text.endswith(":") and gap < 3 * size:
                split = False            # speaker label of a dialogue
            elif not split and gap > 0.35 * size:
                split = gutter(end, r["bbox"][0], size, r["bbox"][1], r["bbox"][3], {r["font"], cur[-1]["font"]})
            elif not split and gap > 0.15 * size:     # narrow gutter between two columns
                split = gutter(end, r["bbox"][0], size, r["bbox"][1], r["bbox"][3],
                               {r["font"], cur[-1]["font"]}, need_sides=True)
            if gap < -0.5 * size:
                split = True             # overlapping text on another layer
            if gap > 0.3 * size and r["font"][:6] != cur[-1]["font"][:6] and not left_text.endswith(":"):
                split = True             # another typeface after a visible gap: a separate element
            if split:
                segs.append(_make_seg(pno, cur))
                cur = [r]
            else:
                cur.append(r)
        segs.append(_make_seg(pno, cur))
    # drop exact duplicates (text drawn twice at the same place)
    out = []
    for s in segs:
        if any(o.text == s.text and abs(o.x0 - s.x0) < 3 and abs(o.y0 - s.y0) < 3 for o in out):
            continue
        out.append(s)
    return out


# ── Reading order ────────────────────────────────────────────────────────────

def _gaps(intervals):
    """Largest gap between merged intervals: (gap, cut position) or None."""
    iv = sorted(intervals)
    best = None
    end = iv[0][1]
    for a, b in iv[1:]:
        if a > end:
            g = a - end
            if best is None or g > best[0]:
                best = (g, (a + end) / 2)
        end = max(end, b)
    return best


def _horizontal_cut(segs):
    """Where to cut a region horizontally.

    If narrow lines form columns (a gutter that only some wide lines cross),
    cut only next to those wide lines, so a column is never split in two.
    Otherwise cut at the widest horizontal gap."""
    iv = sorted((s.y0, s.y1) for s in segs)
    bands = [list(iv[0])]
    for a, b in iv[1:]:
        if a > bands[-1][1]:
            bands.append([a, b])
        else:
            bands[-1][1] = max(bands[-1][1], b)
    if len(bands) < 2:
        return None
    width = max(s.x1 for s in segs) - min(s.x0 for s in segs)
    narrow = [s for s in segs if s.w < 0.55 * width]
    g = _gaps([(s.x0, s.x1) for s in narrow]) if len(narrow) >= 4 else None
    if g and g[0] >= 8:
        gx = g[1]
        spanning = [s for s in segs if s.x0 < gx < s.x1]
        for (a0, a1), (b0, b1) in zip(bands, bands[1:]):
            if any(a0 <= s.y0 and s.y1 <= a1 for s in spanning) or \
               any(b0 <= s.y0 and s.y1 <= b1 for s in spanning):
                return (a1 + b0) / 2
    best = max(zip(bands, bands[1:]), key=lambda ab: ab[1][0] - ab[0][1])
    return (best[0][1] + best[1][0]) / 2


def _two_columns(left, right):
    """Both sides of a vertical gap are columns of text that run side by side
    (stanza gaps lined up across the columns must not split them)."""
    if len(left) < 3 or len(right) < 3:
        return False
    l0, l1 = min(s.y0 for s in left), max(s.y1 for s in left)
    r0, r1 = min(s.y0 for s in right), max(s.y1 for s in right)
    overlap = min(l1, r1) - max(l0, r0)
    return overlap >= 0.6 * min(l1 - l0, r1 - r0)


def xycut(segs, path=()):
    """Recursive XY-cut. Returns segs in reading order with .col set."""
    if len(segs) <= 1:
        for s in segs:
            s.col = path
        return list(segs)
    v = _gaps([(s.x0, s.x1) for s in segs])
    h = _gaps([(s.y0, s.y1) for s in segs])
    if v and v[0] >= 8:
        left = [s for s in segs if s.x1 <= v[1]]
        right = [s for s in segs if s.x1 > v[1]]
        if not h or v[0] >= h[0]:
            return xycut(left, path + (0,)) + xycut(right, path + (1,))
    cut = _horizontal_cut(segs)
    if cut is not None:
        top = [s for s in segs if s.y1 <= cut]
        bottom = [s for s in segs if s.y1 > cut]
        return xycut(top, path) + xycut(bottom, path)
    segs = sorted(segs, key=lambda s: (round(s.y0), s.x0))
    for s in segs:
        s.col = path
    return segs


# ── Book analysis ────────────────────────────────────────────────────────────

def _norm_running(text):
    t = strip_accents(text.lower())
    t = re.sub(r"\d+", "#", t)
    return re.sub(r"[\s•●.]+", "", t)


class Book:
    def __init__(self, source_id, label, series, path):
        self.source_id, self.label, self.series = source_id, label, series
        self.cfg = SERIES[series]
        self.doc = fitz.open(path)
        self.n = len(self.doc)
        self.H = self.doc[min(10, self.n - 1)].rect.height
        self.pages = {}
        for i, page in enumerate(self.doc):
            self.pages[i + 1] = page_segments(page, i + 1)
        self._find_running()
        self.running_texts = {_norm_running(s.text) for segs in self.pages.values() for s in segs
                              if s.kind == "running" and len(_norm_running(s.text)) >= 12}
        self._body_size()
        self._page_offset()
        self.toc = self._parse_toc()

    # Running headers/footers: same text at the same place on many pages,
    # same text in the top/bottom band on many pages, or a longer text that
    # recurs on many pages anywhere (lesson tabs that move with the lesson).
    def _find_running(self):
        pos, zone, anywhere = defaultdict(set), defaultdict(set), defaultdict(set)
        for p, segs in self.pages.items():
            for s in segs:
                k = _norm_running(s.text)
                if not k:
                    continue
                anywhere[k].add(p)
                pos[(k, round(s.y0 / 6), round(s.x0 / 12))].add(p)
                z = "top" if s.y1 < 0.13 * self.H else "bottom" if s.y0 > 0.88 * self.H else None
                if z:
                    zone[(k, z)].add(p)
        limit = max(3, int(0.05 * self.n))
        for p, segs in self.pages.items():
            for s in segs:
                k = _norm_running(s.text)
                z = "top" if s.y1 < 0.13 * self.H else "bottom" if s.y0 > 0.88 * self.H else None
                if (len(k) >= 8 and len(anywhere[k]) >= 6) or \
                   (len(k) >= 3 and len(pos[(k, round(s.y0 / 6), round(s.x0 / 12))]) >= limit) or \
                   (z and k and len(zone[(k, z)]) >= limit) or \
                   (z and re.fullmatch(r"\d{1,3}", s.text)):
                    s.kind = "running"

    def _body_size(self):
        c = Counter()
        for segs in self.pages.values():
            for s in segs:
                if s.kind != "running" and greek_ratio(s.text) > 0.6:
                    c[round(s.size * 2) / 2] += len(s.text)
        self.body = c.most_common(1)[0][0]
        self.body_min = self.cfg.get("body_min", 0.95 * self.body)
        self.body_max = 1.3 * max(self.body, self.body_min)

    def _page_offset(self):
        c = Counter()
        for p, segs in self.pages.items():
            for s in segs:
                if s.kind == "running" and re.fullmatch(r"\d{1,3}", s.text):
                    c[p - int(s.text)] += 1
        self.offset = c.most_common(1)[0][0] if c else 0

    def _parse_toc(self):
        """{pdf_page: title} from 'Title ......... 12' lines of the contents page."""
        toc = {}
        for p in range(1, min(12, self.n) + 1):
            segs = self.pages[p]
            if not any(re.search(r"Περιεχόμενα|ΠΕΡΙΕΧΟΜΕΝΑ", s.text) for s in segs):
                continue
            prev = None
            for s in sorted(segs, key=lambda s: (round(s.y0), s.x0)):
                m = re.match(r"^(.*?)[\s.…]*\.{4,}[\s.]*(\d{1,3})\s*$", s.text)
                if m:
                    title = m.group(1).strip(" .")
                    if not title and prev is not None and re.search(r"[^\W\d_]{3}", prev.text):
                        title = prev.text.strip(" .")
                    title = re.sub(r"^\d{1,2}[.)]?\s+", "", title)
                    if title:
                        toc[int(m.group(2)) + self.offset] = title
                prev = s
        return toc

    # ── classification ──
    def classify(self, s):
        if s.kind == "running":
            return
        t = s.text
        if DOTS_ONLY.match(t):
            s.kind = "omission"
            return
        if not re.search(r"[^\W\d_]", t):
            s.kind = "exercise" if re.fullmatch(r"\(?\d{1,2}[.)]?", t) else "decor"
            return
        if greek_ratio(t) < 0.4 and not re.search(r"[A-Za-z]{2,}\s+\d", t):
            s.kind = "decor"
            return
        if font_match(s, self.cfg.get("title")):
            s.kind = "title"
        elif font_match(s, self.cfg.get("weak_title")) and not NUMBERED.match(t):
            s.kind = "weak_title"
        elif font_match(s, self.cfg.get("heading")):
            s.kind = "heading"
        elif NUMBERED.match(t):
            s.kind = "exercise"
        elif s.size < self.body_min:
            s.kind = "small"
        elif s.size > self.body_max:
            s.kind = "decor"
        else:
            s.kind = "body"

    def merge_titles(self, segs):
        """Join title fragments that belong together (curved or multi-line titles)."""
        titles = [s for s in segs if s.kind in ("title", "weak_title")]
        rest = [s for s in segs if s.kind not in ("title", "weak_title")]
        groups = []
        for s in sorted(titles, key=lambda s: (s.y0, s.x0)):
            for g in groups:
                reach = 2.5 if s.frag else 1.5
                if g[0].kind == s.kind and g[0].font == s.font and abs(g[0].size - s.size) <= 0.6 and any(
                        s.x0 < o.x1 + reach * s.size and o.x0 < s.x1 + reach * s.size and
                        s.y0 < o.y1 + 0.9 * s.size and o.y0 < s.y1 + 0.9 * s.size for o in g):
                    g.append(s)
                    break
            else:
                groups.append([s])
        merged = []
        for g in groups:
            if len(g) == 1:
                merged.append(g[0])
                continue
            tol = 0.35 * max(o.size for o in g)
            xs = sorted(g, key=lambda o: o.x0)
            disjoint = all(b.x0 >= a.x1 - tol for a, b in zip(xs, xs[1:]))
            if disjoint:   # one line, possibly curved: concatenate fragments left to right
                text = "".join(o.raw or o.text for o in xs)
            else:          # several lines: top to bottom
                text = " ".join(o.text for o in sorted(g, key=lambda o: (o.y0, o.x0)))
            m = Seg(g[0].page, min(o.x0 for o in g), min(o.y0 for o in g), max(o.x1 for o in g),
                    max(o.y1 for o in g), re.sub(r"\s+", " ", text).strip(), g[0].size, g[0].font, g[0].bold)
            m.kind = g[0].kind
            merged.append(m)
        return rest + merged

    def ordered_segments(self):
        """All segments of the book in reading order, classified."""
        out = []
        for p in range(1, self.n + 1):
            segs = self.pages[p]
            for s in segs:
                self.classify(s)
            for s in segs:   # rotated fragments are only kept as title parts
                if s.frag and s.kind != "title":
                    s.kind = "decor"
            live = self.merge_titles([s for s in segs if s.kind not in ("running", "decor")])
            ordered = xycut(live) if live else []
            if self.cfg.get("toc_titles") and p in self.toc:
                first_title = next((s for s in ordered if s.kind == "title"), None)
                if first_title is not None:
                    first_title.text = self.toc[p]
                    # other pieces of the same (curved) title are not new titles
                    tk = _norm_running(self.toc[p])
                    for s in ordered:
                        if s.kind == "title" and s is not first_title and _norm_running(s.text) in tk:
                            s.kind = "decor"
                    ordered = [s for s in ordered if s.kind != "decor"]
            if self.cfg.get("toc_titles") and p in self.toc and not any(s.kind == "title" for s in ordered):
                first = ordered[0] if ordered else None
                t = Seg(p, first.x0 if first else 0, (first.y0 - 1) if first else 0,
                        first.x1 if first else 0, first.y0 if first else 0, self.toc[p], 0, "TOC", False)
                t.kind = "toc_title"
                t.col = first.col if first else ()
                ordered.insert(0, t)
            out.extend(ordered)
        for i, s in enumerate(out):
            s.order = i
        return out


# ── Passages ─────────────────────────────────────────────────────────────────

@dataclass
class Passage:
    title: Seg
    segs: list = field(default_factory=list)
    attribution: list = field(default_factory=list)
    end: str = ""

    @property
    def pages(self):
        ps = [self.title.page] + [s.page for s in self.segs]
        return min(ps), max(ps)


def _regions(segs):
    """Left/right edge and line pitch for each (page, column) of a passage."""
    reg = {}
    by = defaultdict(list)
    for s in segs:
        by[(s.page, s.col)].append(s)
    for k, ss in by.items():
        ys = sorted(s.y0 for s in ss)
        diffs = [b - a for a, b in zip(ys, ys[1:]) if 0.5 * ss[0].size < b - a < 3 * max(o.size for o in ss)]
        pitch = statistics.median(diffs) if diffs else 1.25 * ss[0].size
        reg[k] = dict(left=min(s.x0 for s in ss), right=max(s.x1 for s in ss), pitch=pitch)
    return reg


def _join(cur: str, nxt: str) -> str:
    """Join two lines of the same paragraph, re-joining hyphenated words."""
    cur = re.sub(r"(\w) ([" + HYPHENS + r"])$", r"\1\2", cur.rstrip())
    if cur and cur[-1] in HYPHENS and len(cur) > 1 and cur[-2].isalpha() and nxt[:1].isalpha():
        if cur[-2].islower() == nxt[0].islower():
            return cur[:-1] + nxt
    if len(cur) == 1 and cur.isupper() and nxt[:1].islower():
        return cur + nxt                  # drop cap: "Τ" + "αξιδεύοντας"
    return cur + " " + nxt


def _ends_sentence(text):
    return text.rstrip().endswith(TERMINAL)


def _ragged_prose(segs, reg):
    """Prose set ragged-right: long left-aligned lines that mostly break in
    mid-sentence, the next line going on in lower case. Verse lines are
    shorter, or end with punctuation, or are indented/centred."""
    if len(segs) < 5:
        return False
    words = sum(len(s.text.split()) for s in segs) / len(segs)
    left = open_end = cont = 0
    for i, s in enumerate(segs):
        r = reg[(s.page, s.col)]
        left += s.x0 <= r["left"] + 2
        if not _ends_sentence(s.text) and not s.text.rstrip().endswith((",", ":")):
            open_end += 1
            if i + 1 < len(segs) and segs[i + 1].text[:1].islower():
                cont += 1
    n = len(segs)
    gaps = sum(1 for p, s in zip(segs, segs[1:]) if (p.page, p.col) == (s.page, s.col)
               and s.y0 - p.y0 > 1.33 * reg[(s.page, s.col)]["pitch"])
    if gaps >= 2:                 # stanza spaces: verse
        return False
    return words >= 7 and left / n >= 0.7 and open_end / n >= 0.5 and cont >= 0.6 * open_end


def is_verse(segs, reg, keep_lines):
    if keep_lines:
        return True
    if len(segs) < 4:
        return False
    near = []
    for s in segs:
        r = reg[(s.page, s.col)]
        width = max(r["right"] - r["left"], 1)
        if s.x1 >= r["right"] - 0.02 * width - 1:
            near.append(s)
    if len(near) < 3 or len(near) / len(segs) < 0.25:
        return not _ragged_prose(segs, reg)
    # justified prose: lines that reach the margin end in mid-sentence;
    # long verse lines that reach it mostly end with punctuation
    closed = sum(1 for s in near if _ends_sentence(s.text))
    return closed / len(near) > 0.6


def assemble(segs, keep_lines):
    reg = _regions(segs)
    verse = is_verse(segs, reg, keep_lines)
    if verse:
        return _assemble_verse(segs, reg), "verse"
    return _assemble_prose(segs, reg), "prose"


def _assemble_prose(segs, reg):
    pars = []
    for i, s in enumerate(segs):
        t = s.text
        if DOTS_ONLY.match(t):            # omission marker inside a text
            pars.append(None)
            continue
        if not pars or pars[-1] is None:
            pars.append(t)
            continue
        p = segs[i - 1]
        r = reg[(s.page, s.col)]
        same = (s.page, s.col) == (p.page, p.col)
        nxt = segs[i + 1] if i + 1 < len(segs) and (segs[i + 1].page, segs[i + 1].col) == (s.page, s.col) else None
        ref = min([o.x0 for o in (p if same else None, nxt) if o is not None] or [r["left"]])
        new = bool(DASH_START.match(t) or SPEAKER.match(t))
        hanging = same and bool(DASH_START.match(p.text) or SPEAKER.match(p.text)) and nxt is None
        if not new and not hanging and s.x0 - ref > 0.6 * s.size:
            new = True                    # first-line indent (not the hanging indent under a dash)
        if not new and same and s.y0 - p.y0 > 1.6 * r["pitch"]:
            new = True                    # paragraph space
        if not new:
            pr = reg[(p.page, p.col)]
            if _ends_sentence(p.text) and p.x1 < pr["right"] - 1.5 * p.size:
                new = True                # previous line was a short last line
        prev = pars[-1].rstrip()
        if new and len(prev) > 1 and prev[-1] in HYPHENS and prev[-2].isalpha() and t[:1].islower():
            new = False                   # a word broken over the line end never starts a paragraph
        if new and t[:1].islower() and not _ends_sentence(prev) and not prev.endswith(":"):
            new = False                   # the sentence goes on (text wrapped round a picture)
        if new:
            pars.append(t)
        else:
            pars[-1] = _join(pars[-1], t)
    return "\n".join(x for x in pars if x)


def _assemble_verse(segs, reg):
    # stanza sizes inside columns (bounded by gaps on both sides) give the norm
    breaks = []
    for i, s in enumerate(segs):
        if i == 0:
            breaks.append(False)
            continue
        p = segs[i - 1]
        same = (s.page, s.col) == (p.page, p.col)
        breaks.append(same and s.y0 - p.y0 > 1.33 * reg[(s.page, s.col)]["pitch"])
    sizes, n, closed_start = [], 0, True
    for i, s in enumerate(segs):
        if i and breaks[i]:
            if closed_start:
                sizes.append(n)
            n, closed_start = 0, True
        elif i and (s.page, s.col) != (segs[i - 1].page, segs[i - 1].col):
            n, closed_start = 0, False
        n += 1
    if closed_start:
        sizes.append(n)
    norm = Counter(sizes).most_common(1)[0][0] if sizes else 0

    stanzas, cur, count = [], [], 0
    for i, s in enumerate(segs):
        t = s.text
        if DOTS_ONLY.match(t):
            if cur:
                stanzas.append(cur)
            cur, count = [], 0
            continue
        if cur:
            p = segs[i - 1]
            switch = (s.page, s.col) != (p.page, p.col)
            if breaks[i] or (switch and (_ends_sentence(cur[-1]) or count == norm)):
                stanzas.append(cur)
                cur, count = [], 0
            elif cur[-1].rstrip()[-1:] in HYPHENS and t[:1].islower():
                cur[-1] = _join(cur[-1], t)
                continue
        cur.append(re.sub(r"(\w) ([" + HYPHENS + r"])$", r"\1\2", t))
        count += 1
    if cur:
        stanzas.append(cur)
    return "\n\n".join("\n".join(st) for st in stanzas)


def _question_list_at_end(lines):
    """Three or more questions, each starting on its own line, close the text."""
    count, i = 0, len(lines) - 1
    while i >= 0 and lines[i].rstrip().endswith((";", ";")):
        start = i
        if i > 0 and not _ends_sentence(lines[i - 1]):
            start = i - 1                 # a question wrapped over two lines
        count += 1
        i = start - 1
    return count >= 3


def clean_text(text):
    text = text.replace("­", "")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)   # invisible control glyphs
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" +\n", "\n", text)
    return text.strip()


class Extractor:
    def __init__(self, book: Book, chapters=None):
        self.chapters = chapters or {}
        self.b = book
        self.cfg = book.cfg
        self.passages = []
        self.uncertain = []

    # lookahead: next segment that matters for the flow
    def _next_meaningful(self, segs, i):
        for j in range(i, len(segs)):
            s = segs[j]
            if s.kind in ("decor", "running"):
                continue
            if s.kind == "small" and s.text.startswith("*"):
                continue
            return s
        return None

    def run(self):
        segs = self.b.ordered_segments()
        cur = None
        untitled = []
        i = 0
        while i < len(segs):
            s = segs[i]
            k = s.kind
            if cur and self.cfg.get("single_page") and s.page != cur.title.page:
                self._close(cur, "page_end")
                cur = None
            if cur and cur.segs and k == "body" and s.page != cur.segs[-1].page and s.bold and                     len(s.text.split()) <= 6 and not _ends_sentence(s.text):
                self._close(cur, "new_box")        # the next page opens with another box's heading
                cur = None
            if cur and cur.segs and s.page - cur.segs[-1].page > 1:
                self._close(cur, "page_gap")
                cur = None
            if k in ("title", "weak_title", "toc_title"):
                if cur:
                    self._close(cur, "next_title")
                self._flush_untitled(untitled)
                untitled = []
                cur = Passage(title=s)
                i += 1
                continue
            if cur is None:
                if k == "body" and not starts_with_exercise_verb(s.text):
                    untitled.append(s)
                elif k in ("heading", "exercise") or (k == "body" and starts_with_exercise_verb(s.text)):
                    self._flush_untitled(untitled)
                    untitled = []
                i += 1
                continue
            # inside a passage
            if k in ("heading", "exercise"):
                self._close(cur, k)
                cur = None
                i += 1
                continue
            if k == "omission":
                if cur.segs:
                    cur.segs.append(s)
                i += 1
                continue
            if k == "body":
                if cur.segs and starts_with_exercise_verb(s.text) and self._starts_paragraph(cur, s):
                    self._close(cur, "exercise_verb")
                    cur = None
                    i += 1
                    continue
                if not cur.segs and s.bold and len(s.text.split()) <= 6 and s.text.rstrip().endswith(":"):
                    i += 1           # text-type label under the title ("άρθρο εφημερίδας:")
                    continue
                cur.segs.append(s)
                i += 1
                continue
            if k == "small":
                if s.text.startswith("*"):          # footnote
                    i += 1
                    continue
                if not cur.segs:                    # caption/subtitle before the text
                    i += 1
                    continue
                j = i
                group = []
                while j < len(segs) and segs[j].kind in ("small", "decor", "running"):
                    if segs[j].kind == "small" and not segs[j].text.startswith("*"):
                        group.append(segs[j])
                    j += 1
                verdict = self._small_group(cur, group, self._next_meaningful(segs, j))
                if verdict == "attribution":
                    cur.attribution = group
                    self._close(cur, "attribution")
                    cur = None
                elif verdict == "inline":
                    cur.segs.extend(group)
                i = j
                continue
            i += 1
        if cur:
            self._close(cur, "end_of_book")
        self._flush_untitled(untitled)
        return self.passages, self.uncertain

    def _starts_paragraph(self, cur, s):
        p = cur.segs[-1]
        return p.page != s.page or p.col != s.col or _ends_sentence(p.text)

    def _small_group(self, cur, group, nxt):
        """Is a run of small type the attribution, an in-text line, or a caption?"""
        body = [o for o in cur.segs if o.page == group[0].page] or cur.segs[-3:]
        left = min(o.x0 for o in body)
        right = max(o.x1 for o in body)
        width = max(right - left, 1)
        text = " ".join(o.text for o in group)
        offset = min(o.x0 for o in group) > left + 0.15 * width
        cue = bool(ATTRIBUTION_CUES.search(text))
        # a source line names someone or something: it starts with a capital,
        # a quote or a bracket and is not a label ending in ':'
        source_like = bool(re.match(r"[«(\"A-ZΑ-ΩΆ-Ώ]", text)) and not text.rstrip().endswith(":") \
            and len(text.split()) <= 25
        continues = (nxt is not None and nxt.kind == "body" and not starts_with_exercise_verb(nxt.text))
        last = cur.segs[-1]
        gx0 = min(o.x0 for o in group)
        gx1 = max(o.x1 for o in group)
        beside = min(gx1, last.x1) - max(gx0, last.x0) <= 0   # next to the text column, not under it
        if continues and all(o.size < 0.65 * self.b.body for o in group) and \
                (nxt.page == group[0].page or not _ends_sentence(last.text) or beside):
            return "caption"            # far smaller than any source line, and the text goes on
        if cue:
            return "attribution"
        if continues and group[0].page == last.page and group[0].y0 < last.y1 - 1:
            return "caption"            # not under the text but beside it: a picture caption
        if offset and source_like:
            return "attribution"
        if not continues and source_like:
            return "attribution"
        if not continues:
            return "caption"
        if abs(gx0 - left) <= 0.05 * width and text.lstrip().startswith("("):
            return "inline"             # stage direction in a play
        return "caption"

    def _close(self, cur, reason):
        cur.end = reason
        body = [s for s in cur.segs if s.kind in ("body", "small", "omission")]
        while body and body[-1].kind == "omission":
            body.pop()
        if self.cfg.get("keep_lines"):
            body = [s for s in body if not self._letter_line(s)]
            # word cards under the text: one or two words set apart, no punctuation
            while len(body) > 1 and len(body[-1].text.split()) <= 2 and not _ends_sentence(body[-1].text) and (
                    (body[-1].page, body[-1].col) != (body[-2].page, body[-2].col)
                    or body[-1].y0 - body[-2].y1 > 1.5 * body[-2].size):
                body.pop()
        title = cur.title.text.strip()
        if not body:
            return
        content, form = assemble(body, self.cfg.get("keep_lines", False))
        content = clean_text(content)
        problems = []
        tier = cur.title.kind
        attr = " ".join(o.text for o in cur.attribution)
        reviewed = False
        end = _reviewed_end(self.b.source_id, cur.title.text)
        if end and reason != "attribution":
            m = re.search(r"\s+".join(map(re.escape, end.split())), content)
            if m:                       # checked by eye: cut after the last printed words
                content, reviewed = content[:m.end()], True
        words = content.split()
        rejected = _reviewed_reject(self.b.source_id, cur.title.text)
        if rejected:
            problems.append("checked by eye: " + rejected)
        if reviewed:
            pass
        elif tier in ("weak_title", "toc_title") and reason != "attribution":
            problems.append(f"title typography is ambiguous and the text has no attribution (ended by {reason})")
        elif tier in ("weak_title", "toc_title") and not (
                ATTRIBUTION_CUES.search(attr) or
                re.fullmatch(r"(?:[«]?[A-ZΑ-ΩΆ-Ώ][^\s,]*[,.»]?\s*){1,6}", re.sub(r"\([^)]*\)\s*", "", attr).strip())):
            problems.append(f"title typography is ambiguous and the line after the text does not name a source: {attr[:60]!r}")
        if reviewed:
            pass
        elif tier == "weak_title" and cur.pages[0] != cur.pages[1]:
            problems.append("title typography is ambiguous and the text runs onto another page")
        elif self.cfg.get("need_attribution") and reason != "attribution":
            problems.append(f"no attribution line; the text ended at {reason}")
        lines = [l for l in content.split("\n") if l.strip()]
        if not _ends_sentence(content):
            problems.append("ends in mid-sentence")
        if content[:1].islower():
            problems.append("starts in mid-sentence or mid-word (first letter not in the text layer?)")
        if form == "prose" and len(set(lines)) < len(lines):
            problems.append("repeated lines")
        if re.search(r"[^\W\d_]{24,}", content):
            problems.append("words run together (the text layer has no spaces here)")
        labels = Counter(l.split(":")[0] for l in lines if TABLE_LINE.match(l))
        table = sum(labels.values()) >= 3 and max(labels.values()) == 1    # distinct labels: a fact sheet
        listy = sum(1 for l in lines if LIST_LINE.match(l))
        if listy >= 3 or table:
            problems.append("list or table, not running text")
        if len(lines) >= 3 and sum(1 for l in lines if l.rstrip().endswith((";", ";"))) / len(lines) >= 0.5:
            problems.append("mostly questions")
        elif _question_list_at_end(lines):
            problems.append("ends with a list of questions (comprehension questions?)")
        if re.search(r"\d \.", content):
            problems.append("a symbol (°, %, …) is missing from the text layer")
        caps = sum(1 for l in lines if re.fullmatch(r"[^a-zα-ωά-ώ]*[Α-ΩA-Z]{3,}[^a-zα-ωά-ώ.!;]*", l))
        if caps >= 2:
            problems.append("contains section labels in capitals")
        if not title[:1].isupper() and not title[:1] in "«\"(":
            problems.append("title is only a fragment of the printed (decorative) title")
        ck = _norm_running(content)
        leak = next((r for r in self.b.running_texts if r in ck), None)
        if leak:
            problems.append("contains a running header or lesson tab")
        if reason in ("end_of_book", "page_gap"):
            problems.append(f"no clear end ({reason})")
        if len(words) < self.cfg.get("min_words", 12):
            problems.append(f"too short ({len(words)} words)")
        if FILL_IN.search(content):
            problems.append("contains fill-in blanks")
        if starts_with_exercise_verb(content):
            problems.append("starts with an exercise instruction")
        sentences = re.findall(r"[^.!;;…]+[.!;;…]", content)
        q = sum(1 for x in sentences if x.endswith((";", ";")))
        if q >= 3 and q / max(len(sentences), 1) > 0.5:
            problems.append("mostly questions")
        if cur.pages[1] - cur.pages[0] > 4:
            problems.append("runs over more than 5 pages")
        if greek_ratio(content) < 0.8:
            problems.append("not Greek text")
        rec = dict(title=title, content=content, page=cur.pages[0], pages=list(cur.pages), form=form,
                   end=reason, attribution=" ".join(o.text for o in cur.attribution))
        if problems:
            self.uncertain.append(dict(source_id=self.b.source_id, book=self.b.label, page=cur.pages[0],
                                       pages=list(cur.pages), title=title, reason="; ".join(problems),
                                       preview=content[:300]))
        else:
            self.passages.append(rec)

    @staticmethod
    def _letter_line(s):
        toks = re.findall(r"[^\W\d_]+", s.text)
        return len(toks) >= 2 and all(len(t) <= 2 for t in toks)   # "Π α", "Ει ει Ει ει", "πα τά τα"

    def _flush_untitled(self, segs):
        if not segs:
            return
        text = " ".join(s.text for s in segs)
        words = text.split()
        if len(words) < max(self.cfg.get("min_words", 12), 20):
            return
        if FILL_IN.search(text) or greek_ratio(text) < 0.8:
            return
        self.uncertain.append(dict(source_id=self.b.source_id, book=self.b.label, page=segs[0].page,
                                   pages=[segs[0].page, segs[-1].page], title="",
                                   reason="text without a lesson title (frame text, text inside an exercise, notice)",
                                   preview=text[:300]))


# ── Chapters ─────────────────────────────────────────────────────────────────

_UNIT = re.compile(r"^(?:ενοτητα|ενοτητα)\s*(\d{1,2})$")


def _despace(t):
    """'Έ ν α  α κ ό μ α' (letter-spaced header) -> 'Ένα ακόμα'."""
    if re.fullmatch(r"(?:\S ){3,}\S.*", t):
        t = " ".join(w.replace(" ", "") for w in re.split(r"\s{2,}", t))
    return t


def toc_units(book: Book):
    """[(pdf_page, 'Ενότητα N — name')] from the contents page, if it lists units.
    Numbered lesson names without page numbers go to book.toc_lessons."""
    units = []
    book.toc_lessons = {}
    for p in range(1, min(12, book.n) + 1):
        if not any(re.search(r"Περιεχόμενα|ΠΕΡΙΕΧΟΜΕΝΑ", s.text) for s in book.pages[p]):
            continue
        segs = book.pages[p]
        rows = []
        for s in sorted(segs, key=lambda s: (s.y0, s.x0)):
            for r in rows:
                a, b = r[0].y0, r[0].y1
                if min(b, s.y1) - max(a, s.y0) > 0.4 * min(b - a, s.y1 - s.y0) and \
                        (s.x0 < 0.5 * book.doc[p - 1].rect.width) == (r[0].x0 < 0.5 * book.doc[p - 1].rect.width):
                    r.append(s)
                    break
            else:
                rows.append([s])
        texts = [re.sub(r"\s+", " ", " ".join(o.text for o in sorted(r, key=lambda o: o.x0))) for r in rows]
        for t in texts:
            m = re.match(r"^(\d{1,2})\s+([^\d.][^.]*?)[\s.…]*(?:\.{3,}[\s.…\d]*)?$", t)
            if m:
                book.toc_lessons[int(m.group(1))] = m.group(2).strip()
        pending = None
        for t in texts:
            m = re.match(r"^(?:ΕΝΟΤΗΤΑ|ENOTHTA)\s*[ΙI]?(\d{1,2})$", t)
            if m:
                pending = int(m.group(1) if len(m.group(1)) > 1 or not re.search(r"[ΙI]\d", t) else "1" + m.group(1))
                continue
            m = re.match(r"^(.*?[^\W\d_].*?)[\s.…]*(?:\.\s?){3,}[\s.…]*(\d{1,3})$", t)
            if pending is not None and m:
                units.append((int(m.group(2)) + book.offset, f"Ενότητα {pending} — {m.group(1).strip(' .')}"))
                pending = None
                continue
            m = re.match(r"^(\d{1,2})\s+([^\d.][^.]*?)[\s.…]*\.{3,}[\s.…]*(\d{1,3})$", t)
            if m:
                units.append((int(m.group(3)) + book.offset, f"Ενότητα {int(m.group(1))} — {m.group(2).strip()}"))
    return sorted(set(units))


def chapter_map(book: Book):
    """Unit label per page: from the contents page when it lists units,
    otherwise from the running header/footer band ("Ενότητα N — name")."""
    units = toc_units(book)
    if units and book.cfg.get("lesson_opener"):
        # lessons whose page number is missing from the contents: find their opening page
        start = {int(re.match(r"Ενότητα (\d+)", l).group(1)): pg for pg, l in units}
        for n, name in sorted(book.toc_lessons.items()):
            if n in start:
                continue
            # the opening page lies between the previous and the next lesson's start
            lo = max([pg for m, pg in start.items() if m < n] or [6]) + 1
            hi = min([pg for m, pg in start.items() if m > n] or [book.n + 1])
            for p in range(lo, hi):
                if any(font_match(o, book.cfg["lesson_opener"]) and _norm_running(o.text) == _norm_running(name)
                       for o in book.pages[p]):
                    units.append((p, f"Ενότητα {n} — {name}"))
                    start[n] = p
                    break
        units = sorted(set(units))
    if len(units) >= 2:
        result, last = {}, None
        for p in range(1, book.n + 1):
            for start, label in units:
                if start <= p:
                    last = label
            result[p] = last
        return result
    zone = defaultdict(list)
    count = Counter()
    for p, segs in book.pages.items():
        for s in segs:
            if s.kind == "running" and (s.y1 < 0.13 * book.H or s.y0 > 0.88 * book.H):
                zone[p].append(s)
                count[_norm_running(s.text)] += 1
    constant = {k for k, c in count.items() if c > 0.35 * book.n}
    best = {}                     # the same header with the fewest stray spaces
    for segs in zone.values():
        for s in segs:
            k = _norm_running(s.text)
            if k not in best or s.text.count(" ") < best[k].count(" "):
                best[k] = s.text
    result, last, unit_name, first_number, by_number = {}, None, None, None, {}
    for p in range(1, book.n + 1):
        opener = [s for s in book.pages[p] if font_match(s, book.cfg.get("unit_title"))]
        if opener:                # unit opening page: the unit name in plain text
            unit_name = re.sub(r"\s+", " ", opener[0].text).strip(" .")
        number, names = None, []
        lessons = getattr(book, "toc_lessons", {})
        if lessons and book.cfg.get("lesson_opener"):
            # a lesson opening page names its lesson; hidden copies of later names may sit
            # on the same page, so take the next lesson number after the current one
            here = {_norm_running(s.text) for s in book.pages[p] if font_match(s, book.cfg["lesson_opener"])}
            current = int(re.match(r"Ενότητα (\d+)", last).group(1)) if last and last.startswith("Ενότητα") else 0
            found = [n for n, nm in sorted(lessons.items()) if n > current and _norm_running(nm) in here]
            if found:
                n = found[0]
                last = by_number.setdefault(n, f"Ενότητα {n} — {lessons[n]}")
        for s in sorted(zone.get(p, []), key=lambda s: (s.y0, s.x0)):
            t = s.text.strip()
            norm = strip_accents(t.lower()).translate(str.maketrans("eo", "εο")).replace(" ", "")
            m = _UNIT.match(norm)
            if m:
                number = int(m.group(1))
            elif re.fullmatch(r"\d{1,2}", t) and s.size >= 1.8 * book.body:
                number = int(t)
            elif _norm_running(t) not in constant and re.search(r"[^\W\d_]{3}", t) \
                    and not re.fullmatch(r"(?:ε ν ο τ η τ α|e n o t h t a|ενοτητα)", strip_accents(t.lower())) \
                    and not font_match(s, book.cfg.get("heading")) \
                    and (s.y1 < 0.13 * book.H or re.search(r"[•●]", t)):   # footers only with the book mark
                t = best.get(_norm_running(t), t) if not re.search(r"\d", t) else t
                names.append((s.size, s.y0, re.sub(r"\s+", " ", _despace(re.split(r"\s*[•●]\s*", t)[0])).strip(" .")))
        # the unit name is the largest header text (two lines of the same size are joined)
        top = max((n[0] for n in names), default=0)
        name = " ".join(dict.fromkeys(n[2] for n in sorted(names, key=lambda n: n[1]) if n[0] == top and n[2]))
        m = re.match(r"^(\d{1,2})\.\s+(.+)$", name)
        if m and not number:            # "10. ΠΡΟΣΟΧΗ! Τι λέει εκεί;"
            number, name = int(m.group(1)), m.group(2)
        if number and not name and unit_name:
            name = unit_name
        if name and not number and last and last.startswith("Ενότητα ") and                 _norm_running(last.split(" — ", 1)[-1].replace("…", "")) == _norm_running(name.replace("…", "")):
            number = int(re.match(r"Ενότητα (\d+)", last).group(1))   # same unit, header without its number
        if name or number:
            label = f"Ενότητα {number} — {name}" if number and name else name or f"Ενότητα {number}"
            if number:            # one label per unit, whatever the header spelling on later pages
                label = by_number.setdefault(number, label)
            last = label
            if first_number is None and number:
                first_number = number
        result[p] = last
    # pages before the first header belong to the first unit found after them
    firsts = [result[p] for p in range(1, book.n + 1) if result[p]]
    if firsts and not getattr(book, "toc_lessons", {}):
        for p in range(7, book.n + 1):
            if result[p] is not None:
                break
            result[p] = firsts[0]
    # pages of the first unit that has no running header yet (Β΄ Τεύχος Α, unit 1)
    if first_number and first_number - 1 in getattr(book, "toc_lessons", {}):
        label = f"Ενότητα {first_number - 1} — {book.toc_lessons[first_number - 1]}"
        for p in range(1, book.n + 1):
            if result[p] is not None:
                break
            if p > 6:
                result[p] = label
    return result


# ── PDF files ────────────────────────────────────────────────────────────────

def resolve_pdf(fname, url, pdf_dir: Path):
    path = pdf_dir / fname
    if path.exists():
        return path
    if not url:
        raise FileNotFoundError(f"{path} not found and no download URL is known")
    import requests
    print(f"  Κατέβασμα {fname} ...")
    r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=180)
    r.raise_for_status()
    pdf_dir.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_bytes(r.content)
    tmp.replace(path)
    return path


# ── Database ─────────────────────────────────────────────────────────────────

def open_db(db_path: Path):
    if db_path.resolve() == PROTECTED_DB.resolve():
        sys.exit("Αρνούμαι να γράψω στο data/reading.db. Δώσε άλλο --db.")
    import database
    database.DB_PATH = db_path          # same schema as the app (users, sessions, texts)
    database.init_db()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE texts ADD COLUMN chapter TEXT")
    except sqlite3.OperationalError:
        pass
    return conn


def write_book(conn, source_id, passages, chapters):
    rows = []
    for n, p in enumerate(sorted(passages, key=lambda p: (p["page"])), start=1):
        rows.append((f"{source_id}_{n:04d}", source_id, p["title"], p["content"],
                     len(p["content"].split()), p["page"], chapters.get(p["page"])))
    with conn:   # one transaction: old rows go only when the new ones are ready
        conn.execute("DELETE FROM texts WHERE source_id = ?", (source_id,))
        conn.executemany("INSERT INTO texts (id, source_id, title, content, word_count, page_number, chapter) "
                         "VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


# ── CLI ──────────────────────────────────────────────────────────────────────

def debug_page(book: Book, page: int):
    segs = [s for s in book.ordered_segments() if s.page == page]
    print(f"body={book.body} body_min={book.body_min:.2f} offset={book.offset} toc={book.toc.get(page)}")
    for s in segs:
        print(f"{s.kind:10} col={''.join(map(str, s.col)) or '-':4} x{s.x0:4.0f}-{s.x1:4.0f} y{s.y0:4.0f} "
              f"{s.size:4.1f} {s.font[:14]:14} | {s.text}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf-dir", default=str(DEFAULT_PDF_DIR))
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--only", nargs="*", help="source_id(s) to extract")
    ap.add_argument("--debug", help="source_id:page — print the classified segments of a page")
    ap.add_argument("--review", default=str(REVIEW_FILE))
    ap.add_argument("--publish", action="store_true",
                    help="after a run without errors, copy the texts into data/reading.db "
                         "(users and sessions are kept, a backup is made first)")
    args = ap.parse_args()
    pdf_dir = Path(args.pdf_dir)

    if args.debug:
        sid, page = args.debug.split(":")
        sid_, label, series, fname, url = next(b for b in BOOKS if b[0] == sid)
        debug_page(Book(sid, label, series, resolve_pdf(fname, url, pdf_dir)), int(page))
        return

    conn = open_db(Path(args.db))
    review_path = Path(args.review)
    review = []
    if args.only and review_path.exists():
        review = [r for r in json.loads(review_path.read_text(encoding="utf-8")) if r["source_id"] not in args.only]
    summary = []
    for sid, label, series, fname, url in BOOKS:
        if args.only and sid not in args.only:
            continue
        print(f"\n{'=' * 60}\n{label}  ({sid})\n{'=' * 60}")
        try:
            book = Book(sid, label, series, resolve_pdf(fname, url, pdf_dir))
            chapters = chapter_map(book)
            passages, uncertain = Extractor(book, chapters).run()
        except Exception as e:  # keep the old rows of this book
            print(f"  ΣΦΑΛΜΑ: {e} — τα υπάρχοντα κείμενα της πηγής δεν άλλαξαν")
            import traceback
            traceback.print_exc()
            summary.append((sid, "ERROR", 0))
            continue
        n = write_book(conn, sid, passages, chapters)
        review.extend(uncertain)
        for p in sorted(passages, key=lambda p: p["page"]):
            print(f"  σ.{p['page']:3d}  {p['form']:5}  {p['title'][:45]:45}  ({len(p['content'].split())} λέξ.)")
        print(f"  -> {n} κείμενα, {len(uncertain)} αβέβαια")
        summary.append((sid, n, len(uncertain)))
    conn.close()
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\nΣύνοψη (πηγή, κείμενα, αβέβαια):")
    for row in summary:
        print("  ", *row)
    print(f"Βάση: {args.db}\nΑβέβαια: {review_path}")
    if args.publish:
        if any(row[1] == "ERROR" for row in summary):
            sys.exit("Δεν έγινε δημοσίευση: κάποια βιβλία απέτυχαν. Το data/reading.db δεν άλλαξε.")
        publish(Path(args.db))


def publish(new_db: Path):
    """Copy the texts of new_db into the app database (data/reading.db).
    Users and sessions stay; the previous database is backed up first."""
    import shutil
    import time
    if PROTECTED_DB.exists():
        backup = PROTECTED_DB.with_name(f"reading_backup_{time.strftime('%Y-%m-%d_%H%M%S')}.db")
        shutil.copy2(PROTECTED_DB, backup)
        print(f"Αντίγραφο ασφαλείας: {backup}")
    import database
    database.DB_PATH = PROTECTED_DB
    database.init_db()
    conn = sqlite3.connect(PROTECTED_DB, timeout=30)
    try:
        conn.execute("ALTER TABLE texts ADD COLUMN chapter TEXT")
    except sqlite3.OperationalError:
        pass
    conn.execute("ATTACH ? AS new", (str(new_db),))
    cols = "id, source_id, title, content, word_count, page_number, chapter"
    with conn:                   # one transaction: the app never sees a half-filled table
        conn.execute("DELETE FROM texts")
        conn.execute(f"INSERT INTO texts ({cols}) SELECT {cols} FROM new.texts")
    n = conn.execute("SELECT COUNT(*) FROM texts").fetchone()[0]
    conn.execute("DETACH new")
    conn.close()
    print(f"Δημοσιεύτηκαν {n} κείμενα στο {PROTECTED_DB}")


if __name__ == "__main__":
    main()
