import sqlite3
import re
import time

conn = sqlite3.connect('data/external/catalogs.sqlite')
conn.row_factory = sqlite3.Row
c = conn.cursor()

def search_smart(name_query):
    t0 = time.time()
    name_clean = name_query.strip().upper()
    
    # extraer palabras largas para FTS
    # quitamos comillas y caracteres raros
    name_fts = re.sub(r'[^\w\s]', ' ', name_clean)
    words = [w for w in name_fts.split() if len(w) > 3]
    
    # ordenar por longitud y coger las 3 mas largas
    longest_words = sorted(words, key=len, reverse=True)[:3]
    
    match_q = " ".join([f'"{w}"' for w in longest_words])
    
    print(f"Buscando match_q: {match_q}")
    c.execute('''
        SELECT e.ruc, e.razon_social 
        FROM entities_fts fts
        JOIN entities e ON fts.ruc = e.ruc
        WHERE fts.razon_social MATCH ?
        LIMIT 50
    ''', (match_q,))
    res = c.fetchall()
    
    # post filtro en memoria
    # normalizar db_name como lo hace deduplicator
    def normalize_for_compare(n):
        n = n.upper()
        n = re.sub(r'[\"\'\“\”\.,;]', '', n)
        n = re.sub(r'\s+', ' ', n).strip()
        return n
        
    target = normalize_for_compare(name_clean)
    
    final = []
    for r in res:
        db_norm = normalize_for_compare(r['razon_social'])
        if target in db_norm or db_norm in target or target == db_norm:
            final.append(r)
            
    t1 = time.time()
    print(f"Time: {t1-t0:.3f}s")
    for r in final:
        print(r['ruc'], r['razon_social'])

search_smart("KORBAN HEALTH ENTERPRISE KLB CIA.LTDA.")
