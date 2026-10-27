"""
ETL Pipeline: Bagy XML Feed -> OpenAI Agentic Commerce Product Feed Spec
Documentação da OpenAI: https://developers.openai.com/commerce/specs/file-upload/products

Uso:
  python convert_feed.py
  python convert_feed.py --test               # Processa apenas 50 itens para teste rápido
  python convert_feed.py --seller "Meu Nome"  # Altera o nome do vendedor
  python convert_feed.py --sheets-id <ID>     # Atualiza diretamente uma planilha Google Sheets (requer service_account.json)
"""

import urllib.request
import xml.etree.ElementTree as ET
import csv
import json
import re
import html
import sys
import time
import argparse
from typing import Dict, Any, List, Optional

if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

FEED_URL_DEFAULT = "https://feeds.app.bagypro.com/946/t9VjVE4TP8MvDFbqrrStJP0817Naj2brA78B"
DEFAULT_SELLER_NAME = "Secret Outlet"

# Produtos a serem excluídos do feed (por título ou por ID de item)
EXCLUDED_TITLES = [
    "embalagem de papel para presente",
    "sacola plástica embalagem para presente",
    "sacola plastica embalagem para presente",
    "embalagem para presente",
]

EXCLUDED_IDS = {
    "5688398",   # Embalagem de papel para presente
    "7494681",   # Sacola plástica Embalagem para presente
    "30452879",  # Embalagem para presente - Caixa
}

def clean_html(raw_html: Optional[str]) -> str:
    """Remove tags HTML, entidades e normaliza espaços para texto puro (máx 5000 chars conforme spec da OpenAI)."""
    if not raw_html:
        return ""
    text = html.unescape(raw_html)
    cleanr = re.compile(r'<.*?>')
    text = re.sub(cleanr, ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:5000]

def parse_price_value(price_str: Optional[str]) -> Optional[float]:
    """Extrai valor numérico de preços no formato '259.99 BRL'."""
    if not price_str:
        return None
    match = re.search(r'([0-9]+(?:\.[0-9]+)?)', price_str.strip())
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None

def normalize_availability(status: Optional[str]) -> str:
    """Mapeia status para os valores aceitos pela OpenAI: in_stock, out_of_stock, pre_order, backorder, unknown."""
    if not status:
        return "unknown"
    status = status.strip().lower()
    valid_statuses = {"in_stock", "out_of_stock", "pre_order", "backorder", "unknown"}
    if status in valid_statuses:
        return status
    if any(k in status for k in ["in stock", "instock", "disponivel", "disponível"]):
        return "in_stock"
    if any(k in status for k in ["out of stock", "outofstock", "esgotado", "indisponivel", "indisponível"]):
        return "out_of_stock"
    return "unknown"

def process_item(item_elem: ET.Element, seller_name: str = DEFAULT_SELLER_NAME) -> Optional[Dict[str, Any]]:
    """Converte um <item> do feed XML no schema exato do catálogo OpenAI Agentic Commerce."""
    data: Dict[str, Any] = {}
    additional_images: List[str] = []

    for elem in item_elem:
        tag = elem.tag.split('}')[-1]
        text_val = (elem.text or "").strip()

        if tag == "additional_image_link" and text_val:
            additional_images.append(text_val)
        elif tag not in data:
            data[tag] = text_val

    item_id = data.get("id")
    title = data.get("title", "")
    description = clean_html(data.get("description", ""))
    url = data.get("link", "")
    brand = data.get("brand", "").strip() or seller_name
    image_url = data.get("image_link", "")
    availability = normalize_availability(data.get("availability"))
    price = data.get("price", "").strip()

    # Campos estritamente obrigatórios pela OpenAI
    if not item_id or not title or not url or not price:
        return None

    # Exclusão de produtos indesejados (por ID ou correspondência no título)
    title_lower = title.strip().lower()
    if item_id in EXCLUDED_IDS or any(exc in title_lower for exc in EXCLUDED_TITLES):
        return None

    # Validação de preço promocional (sale_price): deve ser estritamente menor que price e > 0
    sale_price = data.get("sale_price", "").strip()
    p_num = parse_price_value(price)
    sp_num = parse_price_value(sale_price)
    if sp_num is not None and p_num is not None:
        if not (0 < sp_num < p_num):
            sale_price = ""
    else:
        sale_price = ""

    # Tratamento de Variações e Grupos
    group_id = data.get("item_group_id", "").strip()
    color = data.get("color", "").strip()
    size = data.get("size", "").strip()

    variant_dict = {}
    if color:
        variant_dict["color"] = color
    if size:
        variant_dict["size"] = size

    has_variations = False
    if group_id and group_id != item_id and len(variant_dict) > 0:
        has_variations = True
    elif not group_id:
        group_id = item_id

    # Normalização de atributos opcionais
    gender = data.get("gender", "").strip().lower()
    if gender not in {"male", "female", "unisex"}:
        gender = ""

    age_group = data.get("age_group", "").strip().lower()
    if age_group not in {"newborn", "infant", "toddler", "kids", "adult"}:
        age_group = ""

    condition = data.get("condition", "").strip().lower()
    if condition not in {"new", "refurbished", "used"}:
        condition = "new"

    product_category = data.get("product_type", "").strip()
    gtin = data.get("gtin", "").strip()
    mpn = data.get("mpn", "").strip()

    record = {
        # 9 Campos Básicos Obrigatórios (OpenAI)
        "item_id": item_id,
        "title": title[:150],
        "description": description,
        "url": url,
        "brand": brand,
        "seller_name": seller_name,
        "image_url": image_url,
        "availability": availability,
        "price": price,
        # Agrupamento e Variantes
        "group_id": group_id,
        "listing_has_variations": "true" if has_variations else "false",
        "variant_dict": json.dumps(variant_dict, ensure_ascii=False) if has_variations else "",
        # Preço Promocional
        "sale_price": sale_price if sale_price else "",
        # Categorização & Demografia
        "product_category": product_category,
        "condition": condition,
        "gender": gender,
        "age_group": age_group,
        "color": color,
        "size": size,
        # Códigos Comerciais
        "gtin": gtin if len(gtin) in (8, 12, 13, 14) else "",
        "mpn": mpn,
        # Mídia Adicional
        "additional_image_urls": json.dumps(additional_images) if additional_images else ""
    }

    return record

def update_google_sheets(records: List[Dict[str, Any]], spreadsheet_id: str, credentials_path: str = "service_account.json"):
    """Atualiza a planilha do Google Sheets via API oficial usando gspread."""
    try:
        import gspread
    except ImportError:
        print("[!] Para usar sincronização com Google Sheets, instale gspread: pip install gspread")
        return

    print(f"[*] Conectando ao Google Sheets (ID: {spreadsheet_id})...")
    try:
        gc = gspread.service_account(filename=credentials_path)
        sh = gc.open_by_key(spreadsheet_id)
        worksheet = sh.get_worksheet(0)

        fieldnames = list(records[0].keys())
        values = [fieldnames]
        for r in records:
            values.append([r.get(f, "") for f in fieldnames])

        print(f"[*] Enviando {len(records)} linhas para o Google Sheets em lotes...")
        worksheet.clear()
        
        # Envia em lotes de 5000 linhas para evitar timeout de socket da API do Google
        batch_size = 5000
        for i in range(0, len(values), batch_size):
            batch = values[i:i + batch_size]
            start_row = i + 1
            worksheet.update(f"A{start_row}", batch)
            print(f" -> Lote de {len(batch)} linhas enviado...")

        print("[OK] Planilha do Google Sheets atualizada com sucesso!")
    except Exception as e:
        print(f"[!] Erro ao atualizar Google Sheets: {e}")

def run_pipeline(
    feed_url: str = FEED_URL_DEFAULT,
    seller_name: str = DEFAULT_SELLER_NAME,
    csv_output_path: str = "openai_products_feed.csv",
    jsonl_output_path: str = "openai_products_feed.jsonl",
    max_items: Optional[int] = None,
    sheets_id: Optional[str] = None,
    sheets_creds: str = "service_account.json"
):
    print(f"[*] Baixando feed XML de {feed_url} ...")
    start_time = time.time()
    req = urllib.request.Request(feed_url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    
    with urllib.request.urlopen(req) as resp:
        print("[*] Processando estrutura XML por streaming ...")
        context = ET.iterparse(resp, events=("end",))
        
        records = []
        count = 0
        
        for event, elem in context:
            if elem.tag.endswith("item"):
                rec = process_item(elem, seller_name=seller_name)
                if rec:
                    records.append(rec)
                    count += 1
                    if count % 5000 == 0:
                        print(f" -> Processados {count} itens...")
                elem.clear()
                if max_items and count >= max_items:
                    break

    download_and_parse_time = time.time() - start_time
    print(f"[OK] {len(records)} itens processados com sucesso em {download_and_parse_time:.2f}s!")

    # 1. Exporta CSV (perfeito para upload na OpenAI ou importar no Google Sheets)
    print(f"[*] Exportando para CSV: {csv_output_path} ...")
    if records:
        fieldnames = list(records[0].keys())
        with open(csv_output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL)
            writer.writeheader()
            writer.writerows(records)

    # 2. Exporta JSONL (formato recomendado pela OpenAI para File Upload)
    print(f"[*] Exportando para JSONL: {jsonl_output_path} ...")
    with open(jsonl_output_path, "w", encoding="utf-8") as f:
        for r in records:
            clean_r = dict(r)
            clean_r["listing_has_variations"] = (clean_r["listing_has_variations"] == "true")
            if clean_r["variant_dict"]:
                clean_r["variant_dict"] = json.loads(clean_r["variant_dict"])
            else:
                clean_r.pop("variant_dict", None)
            if clean_r["additional_image_urls"]:
                clean_r["additional_image_urls"] = json.loads(clean_r["additional_image_urls"])
            else:
                clean_r.pop("additional_image_urls", None)
            
            compact_r = {k: v for k, v in clean_r.items() if v not in ("", None, [])}
            f.write(json.dumps(compact_r, ensure_ascii=False) + "\n")

    total_time = time.time() - start_time
    print(f"[OK] Concluido em {total_time:.2f} segundos!")
    print(f"Arquivos gerados:")
    print(f" - CSV:   {csv_output_path}")
    print(f" - JSONL: {jsonl_output_path}")

    # 3. Opcional: Atualizar Google Sheets diretamente via API
    if sheets_id:
        update_google_sheets(records, sheets_id, sheets_creds)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bagy XML Feed to OpenAI Agentic Commerce Spec Converter")
    parser.add_argument("--test", action="store_true", help="Processa apenas 50 itens para teste rápido")
    parser.add_argument("--seller", type=str, default=DEFAULT_SELLER_NAME, help="Nome do vendedor (seller_name)")
    parser.add_argument("--sheets-id", type=str, default=None, help="ID da planilha do Google Sheets para atualizar")
    parser.add_argument("--sheets-creds", type=str, default="service_account.json", help="Caminho do arquivo de credenciais da conta de serviço Google")
    args = parser.parse_args()

    limit = 50 if args.test else None
    run_pipeline(
        seller_name=args.seller,
        max_items=limit,
        sheets_id=args.sheets_id,
        sheets_creds=args.sheets_creds
    )
