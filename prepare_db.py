"""
Script di preprocessing one-time.
Estrae da food.parquet (Open Food Facts) un CSV leggero con prodotti italiani.
Eseguire una volta: python3 prepare_db.py
"""

import re
import pyarrow.parquet as pq
import pandas as pd

PARQUET_FILE = "food.parquet"
OUTPUT_FILE  = "food_db.csv"

# ==============================================================================
# VALIDAZIONE NOMI
# ==============================================================================

# Caratteri validi in un nome alimentare italiano
_RE_LETTERS = re.compile(r'[a-zA-ZàèéìòùÀÈÉÌÒÙäöüÄÖÜ]{3,}')
_RE_BARCODE  = re.compile(r'^\d[\d\s\-]{5,}$')          # stringhe quasi solo numeriche
_RE_CODE     = re.compile(r'^[A-Z0-9]{6,}$')             # codici tipo "0103HP", "ABCD1234"
_RE_JUNK     = re.compile(r'^[\d\.\-\s/\\#@]{1,}$')      # solo simboli/numeri

_RE_VOWELS = re.compile(r'[aeiouàèéìòùAEIOUÀÈÉÌÒÙ]')

def is_valid_name(name: str) -> bool:
    """Restituisce True se il nome sembra un alimento reale."""
    name = name.strip()
    if len(name) < 4:
        return False
    # Troppi digit (es. codici a barre nel nome)
    n_digits = sum(c.isdigit() for c in name)
    if n_digits / len(name) > 0.45:
        return False
    # Formato codice a barre o codice alfanumerico
    if _RE_BARCODE.match(name) or _RE_CODE.match(name) or _RE_JUNK.match(name):
        return False
    # Deve contenere almeno 3 lettere consecutive
    if not _RE_LETTERS.search(name):
        return False
    # Deve avere almeno una vocale (filtra stringhe tipo "ehqgvh", "bcdfg")
    letters = [c for c in name if c.isalpha()]
    if not letters:
        return False
    vowel_ratio = len(_RE_VOWELS.findall(name)) / len(letters)
    if vowel_ratio < 0.25:
        return False
    return True

def is_valid_brand(brand: str) -> bool:
    """Restituisce True se il nome marca sembra reale (non un codice/barcode)."""
    if not brand:
        return False
    if _RE_BARCODE.match(brand) or _RE_CODE.match(brand):
        return False
    n_digits = sum(c.isdigit() for c in brand)
    if len(brand) > 0 and n_digits / len(brand) > 0.5:
        return False
    if not _RE_LETTERS.search(brand):
        return False
    return True

# ==============================================================================
# ESTRAZIONE
# ==============================================================================

def is_italian(row):
    ct = row["countries_tags"]
    if ct is not None:
        try:
            if any("italy" in str(x).lower() for x in ct):
                return True
        except Exception:
            pass
    lang = row["lang"]
    return isinstance(lang, str) and lang.lower() == "it"

def get_name(product_name_list):
    if product_name_list is None:
        return None
    it_name = fallback = None
    for entry in product_name_list:
        if not isinstance(entry, dict):
            continue
        lang = str(entry.get("lang", ""))
        text = str(entry.get("text", "")).strip()
        if not text:
            continue
        if lang == "it":
            it_name = text
        if fallback is None:
            fallback = text
    return it_name or fallback

def get_nutriment(nutriments, key):
    if nutriments is None:
        return None
    for n in nutriments:
        if isinstance(n, dict) and n.get("name") == key:
            v = n.get("100g")
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None
    return None

def get_category(cats):
    if cats is None:
        return ""
    try:
        for c in cats:
            s = str(c)
            if s.startswith("it:"):
                return s[3:].replace("-", " ").title()
            elif s.startswith("en:"):
                return s[3:].replace("-", " ").title()
    except Exception:
        pass
    return ""

# ==============================================================================
# MAIN
# ==============================================================================

print(f"Apertura {PARQUET_FILE} ...")
pf = pq.ParquetFile(PARQUET_FILE)
print(f"Righe totali: {pf.metadata.num_rows:,}")

records = []
processed = 0

for batch in pf.iter_batches(
    batch_size=100_000,
    columns=["product_name", "nutriments", "categories_tags", "countries_tags", "lang", "brands", "code"]
):
    df = batch.to_pandas()
    processed += len(df)

    for _, row in df[df.apply(is_italian, axis=1)].iterrows():
        name = get_name(row.get("product_name"))
        if not name or not is_valid_name(name):
            continue

        kcal = get_nutriment(row.get("nutriments"), "energy-kcal")
        prot = get_nutriment(row.get("nutriments"), "proteins")
        carb = get_nutriment(row.get("nutriments"), "carbohydrates")
        fat  = get_nutriment(row.get("nutriments"), "fat")

        if kcal is None and prot is None:
            continue

        # Valori fisicamente impossibili → scarta
        if kcal is not None and (kcal < 0 or kcal > 900):
            continue
        if prot is not None and prot > 100:
            continue

        marca_raw = row.get("brands")
        marca_str = str(marca_raw).split(",")[0].strip() if marca_raw and str(marca_raw) != "nan" else ""
        marca = marca_str if is_valid_brand(marca_str) else ""

        cat = get_category(row.get("categories_tags"))

        barcode_raw = row.get("code")
        barcode = str(barcode_raw).strip() if barcode_raw and str(barcode_raw) not in ("nan","None","") else ""

        records.append({
            "Alimento_Nome":      name,
            "Marca":              marca,
            "Barcode":            barcode,
            "Kcal_100g":          round(kcal or 0.0, 1),
            "Pro_100g":           round(prot or 0.0, 2),
            "Cho_100g":           round(carb or 0.0, 2),
            "Fat_100g":           round(fat  or 0.0, 2),
            "Categoria_Alimento": cat,
        })

    if processed % 500_000 == 0:
        print(f"  Processati {processed:,} | Trovati {len(records):,} prodotti validi")

result_df = (
    pd.DataFrame(records)
    .drop_duplicates(subset="Alimento_Nome")
    .sort_values("Alimento_Nome")
    .reset_index(drop=True)
)
result_df.to_csv(OUTPUT_FILE, index=False)
print(f"\nDone. {len(result_df):,} prodotti salvati in {OUTPUT_FILE}")
