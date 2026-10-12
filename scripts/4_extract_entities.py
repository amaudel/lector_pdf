import os
import json
import argparse
import sys
import time
import fitz
import base64
from pathlib import Path
from datetime import datetime

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: La librería 'openai' no está instalada. Ejecuta: pip install openai")
    sys.exit(1)

PROMPT_TEMPLATE = """
Eres un extractor de datos conservador y estricto especializado en documentos legales/administrativos de Ecuador.
Tu única tarea es leer el siguiente TEXTO EXTRAÍDO de una página PDF e identificar menciones explícitas a entidades empresariales, compañías, cooperativas, instituciones públicas o personas naturales con negocio.

REGLAS ESTRICTAS DE EXTRACCIÓN ("CERO ALUCINACIÓN"):
1. NO inventes ni infieras datos que no estén escritos literalmente en el texto.
2. Si aparece un RUC (generalmente 13 dígitos numéricos terminados en 001) extráelo SOLO si está explícitamente contenido en el texto. Si no hay, pon null.
3. Si un RUC parece pertenecer a otra entidad (cruces), trata de no mezclarlo.
4. "razon_social_original" debe ser el texto tal cual aparece. No corrijas faltas ortográficas.
5. "provincia_mencionada" extráela solo si el texto dice la provincia explícitamente asociada a la dirección o ciudad de la empresa.
6. "fragmento_evidencia" debe ser una pequeña cita exacta del texto original (aprox 10-15 palabras) con la que justificas la extracción.
7. "nivel_confianza_extraccion": 
   - ALTA: Tienes Razón Social + RUC claros.
   - MEDIA: Razón Social muy clara, pero sin RUC.
   - BAJA: Mención ambigua, incompleta o parece ser un individuo sin rol empresarial claro.
8. "estado_entidad": 
   - DETECTADA: Para confianzas ALTA o MEDIA.
   - DUDOSA: Para confianza BAJA.
   - Si no hay absolutamente ninguna entidad, devuelve un solo objeto en la lista con estado_entidad="SIN_ENTIDAD_CLARA" y los demás campos null.
9. IGNORA Y OMITE OBLIGATORIAMENTE las menciones al "Instituto Ecuatoriano de Seguridad Social" (IESS) y al "Servicio de Rentas Internas" (SRI). JAMAS los extraigas como entidades empresariales.
10. IGNORA Y OMITE OBLIGATORIAMENTE a las entidades, personas o cargos que figuren únicamente como remitentes o destinatarios en las cabeceras de memorandos u oficios (usualmente indicados en campos como DE:, PARA:, De:, Para:, A:, Remitente:, Destinatario:). Concéntrate únicamente en extraer las entidades que sean el sujeto u objeto de las resoluciones o cuerpo de texto del documento.

FORMATO DE SALIDA (ESTRICTAMENTE JSON con la clave 'entidades'):
{{
  "entidades": [
    {{
      "razon_social_original": "string o null",
      "ruc_detectado_en_texto": "string o null",
      "provincia_mencionada": "string o null",
      "tipo_entidad_detectada": "string (EMPRESA, COOPERATIVA, AUTORIDAD, COMERCIO, etc) o null",
      "fragmento_evidencia": "string o null",
      "nivel_confianza_extraccion": "ALTA | MEDIA | BAJA",
      "estado_entidad": "DETECTADA | DUDOSA | SIN_ENTIDAD_CLARA"
    }}
  ]
}}

TEXTO EXTRAÍDO (Página de Contexto):
\"\"\"{texto}\"\"\"
"""

def setup_openai():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR CRÍTICO: No se encontró la variable de entorno OPENAI_API_KEY.")
        print("Por favor configúrala antes de ejecutar este script.")
        print("Windows: set OPENAI_API_KEY=tu_clave_aqui")
        print("Linux/Mac: export OPENAI_API_KEY=tu_clave_aqui")
        sys.exit(1)
        
    return OpenAI(api_key=api_key)

def extract_entities(consolidated_path_str, output_dir_str):
    consolidated_path = Path(consolidated_path_str).resolve()
    output_dir = Path(output_dir_str).resolve()

    if not consolidated_path.exists():
        print(f"ERROR: No se encontró el consolidado en {consolidated_path}")
        sys.exit(1)
        
    output_dir.mkdir(parents=True, exist_ok=True)
    client = setup_openai()
    
    # Derivar nombre de lote_base de la entrada (consolidated_[lote_base].jsonl)
    filename = consolidated_path.name
    lote_base = filename.replace("consolidated_", "").replace(".jsonl", "")
    
    entities_file = output_dir / f"entities_extracted_{lote_base}.jsonl"
    report_file = output_dir / f"entity_extraction_report_{lote_base}.json"

    print(f"[*] Iniciando Análisis Semántico (OpenAI) del lote '{lote_base}'...")
    
    total_paginas_analizadas = 0
    total_entidades_detectadas = 0
    total_sin_entidad = 0
    total_errores_api = 0
    try:
        with open(consolidated_path, 'r', encoding='utf-8') as f_in, open(entities_file, 'w', encoding='utf-8') as f_out:
            for line_num, line in enumerate(f_in, 1):
                if not line.strip(): continue
                registro_base = json.loads(line)
                
                texto = registro_base.get("texto_crudo", "")
                estado = registro_base.get("estado_extraccion", "")
                pagina = registro_base.get("pagina_pdf", "N/A")
                archivo_origen = registro_base.get("archivo_origen", "N/A")
                rel_path = registro_base.get("ruta_relativa_en_zip", "")
                
                print(f"  -> Analizando {archivo_origen} (Pág {pagina})...", end=" ", flush=True)
                
                is_scanned = (estado == "SIN_TEXTO" or not texto.strip())
                use_vision = False
                base64_image = None
                
                if is_scanned:
                    base_dir = Path(__file__).resolve().parent.parent
                    pdf_path = base_dir / "data" / "temp" / lote_base / rel_path
                    if pdf_path.exists():
                        try:
                            p_index = int(pagina) - 1
                            with fitz.open(pdf_path) as doc_fitz:
                                if 0 <= p_index < len(doc_fitz):
                                    page_fitz = doc_fitz[p_index]
                                    zoom = 2
                                    mat = fitz.Matrix(zoom, zoom)
                                    pix = page_fitz.get_pixmap(matrix=mat)
                                    img_bytes = pix.tobytes("png")
                                    base64_image = base64.b64encode(img_bytes).decode('utf-8')
                                    use_vision = True
                        except Exception:
                            pass
                
                if not use_vision and (estado != "OK" or not texto):
                    print("[SALTADO: No hay texto OK]")
                    continue
                    
                total_paginas_analizadas += 1
                
                try:
                    if use_vision:
                        print("(OCR Visual)...", end=" ", flush=True)
                        prompt = PROMPT_TEMPLATE.format(texto="[Página escaneada. Por favor analiza visualmente la imagen adjunta]")
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            response_format={ "type": "json_object" },
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": prompt},
                                        {
                                            "type": "image_url",
                                            "image_url": {
                                                "url": f"data:image/png;base64,{base64_image}"
                                            }
                                        }
                                    ]
                                }
                            ],
                            temperature=0.0
                        )
                    else:
                        prompt = PROMPT_TEMPLATE.format(texto=texto)
                        # Llamada a la API de OpenAI (gpt-4o-mini por ratio de velocidad/costo ideal para extracciones largas)
                        response = client.chat.completions.create(
                            model="gpt-4o-mini",
                            response_format={ "type": "json_object" },
                            messages=[
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.0
                        )
                    
                    contenido_json = json.loads(response.choices[0].message.content)
                    entidades_json = contenido_json.get("entidades", [])
                    
                    if not isinstance(entidades_json, list):
                        entidades_json = [entidades_json]
                        
                    entidades_validas_en_pagina = 0
                        
                    for entidad in entidades_json:
                        # Si devuelve arreglo con SIN_ENTIDAD_CLARA
                        if entidad.get("estado_entidad") == "SIN_ENTIDAD_CLARA":
                            total_sin_entidad += 1
                        else:
                            entidades_validas_en_pagina += 1
                            total_entidades_detectadas += 1
                            
                        # Mezclar la metadata del pdf base con el hallazgo del LLM
                        registro_completo = {
                            "lote": registro_base["lote"],
                            "id_documento": registro_base["id_documento"],
                            "archivo_origen": registro_base["archivo_origen"],
                            "ruta_relativa_en_zip": registro_base["ruta_relativa_en_zip"],
                            "pagina_pdf": registro_base["pagina_pdf"],
                            # Campos LLM
                            "razon_social_original": entidad.get("razon_social_original"),
                            "provincia_mencionada": entidad.get("provincia_mencionada"),
                            "ruc_detectado_en_texto": entidad.get("ruc_detectado_en_texto"),
                            "tipo_entidad_detectada": entidad.get("tipo_entidad_detectada"),
                            "fragmento_evidencia": entidad.get("fragmento_evidencia"),
                            "nivel_confianza_extraccion": entidad.get("nivel_confianza_extraccion"),
                            "estado_entidad": entidad.get("estado_entidad")
                        }
                        f_out.write(json.dumps(registro_completo, ensure_ascii=False) + "\n")
                    
                    if entidades_validas_en_pagina > 0:
                        print(f"[OK: {entidades_validas_en_pagina} entidades]")
                    else:
                        print(f"[OK: 0 entidades]")
                        
                except Exception as e:
                    total_errores_api += 1
                    print(f"[ERROR DE API/OPENAI: {str(e)}]")
                    
    except Exception as e:
        print(f"ERROR CRÍTICO LEYENDO CONSOLIDADO: {e}")
        
    report = {
        "lote_base": lote_base,
        "fecha_extraccion_entidades": datetime.now().isoformat(),
        "total_paginas_analizadas": total_paginas_analizadas,
        "total_entidades_detectadas": total_entidades_detectadas,
        "total_paginas_sin_entidad_clara": total_sin_entidad,
        "total_errores_red_api": total_errores_api
    }
    
    with open(report_file, 'w', encoding='utf-8') as rf:
        json.dump(report, rf, ensure_ascii=False, indent=2)
        
    print(f"\n=========================================")
    print(f" RESUMEN EXTRACCIÓN SEMÁNTICA (OPENAI) ")
    print(f"=========================================")
    print(f" Páginas analizadas   : {total_paginas_analizadas}")
    print(f" Entidades detectadas : {total_entidades_detectadas}")
    print(f" Páginas sin entidad  : {total_sin_entidad}")
    print(f" Errores de API       : {total_errores_api}")
    print(f"=========================================")
    print(f"[*] Resultados: {entities_file}")
    print(f"[*] Reporte   : {report_file}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Paso 4: Lee texto consolidado y extrae entidades usando OpenAI Gpt-4o-mini.")
    parser.add_argument("--consolidated_path", required=True, help="Ruta absoluta al consolidated_[lote].jsonl")
    parser.add_argument("--output_dir", required=True, help="Ruta de salida (habitualmente data/output)")
    args = parser.parse_args()
    
    extract_entities(args.consolidated_path, args.output_dir)
