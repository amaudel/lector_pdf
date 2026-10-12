import os
import urllib.request
import urllib.parse
import re
import json
from html.parser import HTMLParser

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

class DDGHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.in_result = False
        self.in_title = False
        self.in_snippet = False
        self.in_url = False
        
        self.current_title = ""
        self.current_snippet = ""
        self.current_url = ""
        
    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get('class', '')
        
        if tag == 'div' and 'result' in cls.split():
            self.in_result = True
            self.current_title = ""
            self.current_snippet = ""
            self.current_url = ""
            
        if self.in_result:
            if tag == 'a' and 'result__snippet' in cls.split():
                self.in_snippet = True
            elif tag == 'a' and 'result__url' in cls.split():
                self.in_url = True
            elif tag == 'a' and 'result__snippet' not in cls.split() and 'result__url' not in cls.split():
                if 'result__snippet' not in cls and 'result__url' not in cls:
                    self.in_title = True
                    href = attrs_dict.get('href', '')
                    if href:
                        match = re.search(r'uddg=([^&]+)', href)
                        if match:
                            self.current_url = urllib.parse.unquote(match.group(1))
                        else:
                            self.current_url = href

    def handle_endtag(self, tag):
        if self.in_result:
            if tag == 'a':
                self.in_snippet = False
                self.in_url = False
                self.in_title = False
            elif tag == 'div':
                if self.current_title or self.current_snippet:
                    self.results.append({
                        "title": self.current_title.strip(),
                        "snippet": self.current_snippet.strip(),
                        "url": self.current_url.strip()
                    })
                    self.in_result = False

    def handle_data(self, data):
        if self.in_result:
            if self.in_title:
                self.current_title += data
            elif self.in_snippet:
                self.current_snippet += data
            elif self.in_url:
                if not self.current_url:
                    self.current_url += data

class WebAdapter:
    """Clase base para adapters web de enriquecimiento (Paso 7B)."""
    
    FUENTE = "DESCONOCIDA"
    
    def __init__(self, modo: str = "REAL"):
        self.modo = modo
        
    def search(self, razon_social: str, provincia: str = None, 
               tipo_entidad: str = None) -> list:
        raise NotImplementedError("El adapter web debe implementar search()")

    def _search_web_and_extract(self, query: str, target_name: str) -> list:
        """Busca en la web usando DuckDuckGo con fallback automático a Yahoo, y extrae con el LLM."""
        results = self._search_ddg(query)
        
        # Si DuckDuckGo no devolvió resultados (CAPTCHA o error), usar Yahoo
        if not results:
            print(f"    [WEB SEARCH] DuckDuckGo no devolvió resultados (posible rate limit/CAPTCHA). Usando Yahoo Search...")
            results = self._search_yahoo(query)
            
        if not results:
            print(f"    [WEB SEARCH] Ningún buscador devolvió resultados para: '{query}'")
            return []
            
        print(f"    [WEB SEARCH] Se encontraron {len(results)} resultados. Extrayendo RUC con GPT-4o-mini...")
        return self._extract_candidates_with_llm(query, target_name, results)

    def _search_ddg(self, query: str) -> list:
        """Realiza una búsqueda en DuckDuckGo HTML y devuelve resultados."""
        url = 'https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(query)
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        try:
            html_content = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
            if 'anomaly-modal__box' in html_content:
                print("    [!] DuckDuckGo detectó anomalía (CAPTCHA).")
                return []
                
            parser = DDGHTMLParser()
            parser.feed(html_content)
            return parser.results
        except Exception as e:
            print(f"    [!] Error de red en DuckDuckGo: {e}")
            return []

    def _search_yahoo(self, query: str) -> list:
        """Realiza una búsqueda en Yahoo Search y devuelve resultados."""
        url = 'https://search.yahoo.com/search?p=' + urllib.parse.quote(query)
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        try:
            html = urllib.request.urlopen(req, timeout=10).read().decode('utf-8')
            
            results = []
            ol_match = re.search(r'<ol[^>]+class="[^"]*searchCenterMiddle[^"]*"[^>]*>(.*?)</ol>', html, re.DOTALL)
            if not ol_match:
                ol_content = html
            else:
                ol_content = ol_match.group(1)
                
            items = re.split(r'<li[^>]*>', ol_content)
            for item in items:
                if len(item.strip()) < 50:
                    continue
                    
                urls = re.findall(r'href="([^"]+)"', item)
                target_url = ""
                for u in urls:
                    if 'yahoo.com' in u and '/RU=' not in u:
                        continue
                    target_url = u
                    break
                    
                if not target_url:
                    continue
                    
                if '/RU=' in target_url:
                    try:
                        ru_part = target_url.split('/RU=')[1].split('/RK=')[0]
                        target_url = urllib.parse.unquote(ru_part)
                    except Exception:
                        pass
                        
                # Skip Yahoo internal pages
                if 'yahoo.com' in target_url and not any(d in target_url for d in ['sri-en-linea.com', 'rucecuador.com', 'sri.gob.ec']):
                    continue
                    
                title = ""
                title_match = re.search(r'<h3[^>]*>(.*?)</h3>', item, re.DOTALL)
                if title_match:
                    title = title_match.group(1)
                else:
                    a_match = re.search(r'<a[^>]*>(.*?)</a>', item, re.DOTALL)
                    if a_match:
                        title = a_match.group(1)
                
                title = re.sub(r'<[^>]+>', ' ', title)
                title = re.sub(r'\s+', ' ', title).strip()
                
                snippet = ""
                snippet_match = re.search(r'<div[^>]+class="[^"]*compText[^"]*"[^>]*>(.*?)</div>', item, re.DOTALL)
                if snippet_match:
                    snippet = snippet_match.group(1)
                    snippet = re.sub(r'<[^>]+>', ' ', snippet)
                    snippet = re.sub(r'\s+', ' ', snippet).strip()
                    
                if title and target_url and len(title) > 3:
                    results.append({
                        "title": title,
                        "url": target_url,
                        "snippet": snippet
                    })
            return results
        except Exception as e:
            print(f"    [!] Error de red en Yahoo Search: {e}")
            return []

    def _extract_candidates_with_llm(self, query: str, target_name: str, search_results: list) -> list:
        """Usa OpenAI (gpt-4o-mini) para parsear los snippets de búsqueda y extraer RUCs válidos."""
        if not search_results:
            return []
            
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key or not OpenAI:
            print("  [!] OpenAI API Key o librería OpenAI no configurada.")
            return []
            
        client = OpenAI(api_key=api_key)
        
        limited_results = search_results[:6]
        
        prompt = f"""
Se realizó una búsqueda en la web en Ecuador para la empresa/entidad ecuatoriana: "{target_name}"
Los resultados de la búsqueda (títulos, fragmentos y URLs) son:
{json.dumps(limited_results, ensure_ascii=False, indent=2)}

Tu tarea es analizar detalladamente estos resultados para identificar y extraer la información oficial de la empresa en Ecuador, específicamente:
1. Su número de RUC (Registro Único de Contribuyentes), que es un número de 13 dígitos terminado en "001".
   - Si no encuentras un RUC explícito de 13 dígitos para esta empresa, NO lo inventes.
   - Asegúrate de que el RUC corresponda realmente a la empresa "{target_name}" o a una variante/nombre comercial muy cercano de ella.
2. Su Razón Social oficial según la superintendencia o SRI.
3. La provincia donde está domiciliada (ej. "AZUAY", "GUAYAS", "PICHINCHA", etc. o null si no se puede deducir).
4. El estado del RUC (ej. "ACTIVO", "SUSPENDIDO", "LIQUIDACION" o null si no se especifica).

Devuelve los candidatos encontrados en el siguiente formato JSON estricto:
{{
  "candidatos": [
    {{
      "ruc": "string (13 dígitos)",
      "razon_social": "string (oficial)",
      "provincia": "string o null",
      "estado": "string o null"
    }}
  ]
}}
Si no encuentras ningún candidato con un RUC de 13 dígitos válido que corresponda a la empresa buscada, devuelve la lista vacía.
"""
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Eres un analista de datos corporativos de Ecuador. Extraes información de RUCs con precisión quirúrgica en formato JSON."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.0
            )
            
            res_content = response.choices[0].message.content
            parsed = json.loads(res_content)
            candidatos = parsed.get("candidatos", [])
            
            valid_candidatos = []
            for c in candidatos:
                ruc = str(c.get("ruc", "")).strip()
                ruc_clean = re.sub(r'\D', '', ruc)
                if len(ruc_clean) == 13 and ruc_clean.endswith("001"):
                    c["ruc"] = ruc_clean
                    valid_candidatos.append(c)
                    
            return valid_candidatos
            
        except Exception as e:
            print(f"  [!] Error llamando a OpenAI para extraer datos web: {e}")
            return []


