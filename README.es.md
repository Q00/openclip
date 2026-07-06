<div align="center">

![OpenClip — el harness de edición de video orquestado por agentes](docs/assets/banner.jpg)

### Tú diriges. Una flota de agentes en paralelo debate los cortes, renderiza y demuestra cada entregable — shorts, formato largo, subtítulos y miniaturas a partir de un único video largo.

*Python entrega las herramientas, los agentes entregan el criterio, el humano aporta el buen gusto.*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

**[Sitio web](https://wpti.dev/openclip/)** · **[Diseño](docs/HARNESS.md)** · **[Referencia de herramientas](skills/oc/tools-reference.md)** · **[Guía del agente](AGENT_GUIDE.md)**

[English](README.md) | [한국어](README.ko.md) | [中文](README.zh-CN.md) | [日本語](README.ja.md) | **Español**

</div>

---

Abre tu agente (probado en Claude Code y Codex; instalable en Cursor y en
cualquier agente que hable el [protocolo de skills](https://github.com/vercel-labs/skills)), apúntalo a un video
y di *"haz shorts de este video"*. El agente orquestador lee un manifiesto de flujo,
**despliega subagentes trabajadores en paralelo** (transcripción, un debate de edición de cortes,
minería de ganchos, subtitulado, miniaturas), y cada render debe sobrevivir a un
**verificador adversarial independiente** antes de publicarse. Tú sigues siendo el director:
guía cualquier decisión sobre la marcha con `oc steer`.

**¿Eres un agente de IA leyendo esto?** Empieza con [`llms.txt`](llms.txt), luego
[`AGENT_GUIDE.md`](AGENT_GUIDE.md) — te encaminan al manifiesto de flujo correcto
y a los contratos de los trabajadores.

## Qué produce

- **shorts verticales** de 30-60 segundos con subtítulos incrustados y sincronizados palabra por palabra
- **candidatos de formato largo** de 8-12 minutos que terminan en una conclusión, no a mitad de frase
- un **original con cortes editados** (silencio/muletillas/repetición debatidos y eliminados, no solo detectados)
- **subtítulos SRT** para `en`, `ko`, `es`, `ja`, `zh-Hans`
- **miniaturas emparejadas con el gancho** (fotograma representativo + titular, o gpt-image)
- un manifiesto, EDL, archivos de evidencia y un registro reanudable para cada ejecución

**Míralo, no te fíes de nuestra palabra:** [docs/examples/](docs/examples/) contiene
artefactos reales de una ejecución de 109 minutos — un fotograma de short subtitulado, una miniatura, el
fragmento de transcripción detrás de un gancho, el SRT, el JSON de evidencia 10/10 y el
registro de reanudación.

## Harness de agentes (`oc`)

OpenClip ahora incluye un **harness orquestado por agentes y guiado por humanos** junto al
pipeline original de una sola ejecución `openclip run`. En lugar de un flujo de trabajo fijo, un
agente orquestador lee un manifiesto de flujo y **despliega subagentes trabajadores en
paralelo** — de modo que un video largo se transcribe, debate y renderiza de forma concurrente —
mientras el humano guía cada decisión creativa.

Cuatro flujos:

1. **`flows/flow1-cutedit.yaml`** — proxy LRF/LRV → STT en paralelo (un trabajador por
   fragmento) → un **debate de edición de cortes** (los proponentes argumentan a través de las lentes de muletillas/ritmo/
   narrativa, un juez las reconcilia) → original con cortes editados + subtítulos.
2. **`flows/flow2-shorts.yaml`** — un video largo → STT en paralelo → minería de ganchos →
   shorts 9:16 subtitulados + miniaturas.
3. **`flows/flow3-assemble.yaml`** — teje N videos en un único formato largo, luego extrae
   sus momentos gancho en shorts (cada short recibe subtítulos + una miniatura).
4. **`flows/flow4-thumbnail.yaml`** — produce miniaturas emparejadas con cada gancho: un
   fotograma representativo con un titular incrustado, y/o una miniatura generada por gpt-image
   impulsada por el subtítulo del gancho.

Piezas clave:

- **Herramientas:** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, acp`. Cada una imprime una línea JSON;
  `oc --help` es la referencia canónica. Consulta `skills/oc/tools-reference.md`.
- **Guía humana:** `oc steer --note "..." --scope "global | <stage> | section:<a>-<b> | <deliverable_id>"`.
  El orquestador lee las directivas abiertas de `oc status` antes de cada oleada y
  las inyecta en los trabajadores. El director nunca queda fuera del proceso.
- **Puerta de evidencia:** un `oc-verifier` independiente comprueba cada render frente a
  la evidencia observable y las clases de fallo adversariales; solo un veredicto `confirmed`
  avanza. Un hook `SubagentStop` bloquea el "hecho sin evidencia".
- **Runtime dual:** Claude Code (`.claude/agents`, `.claude/skills/oc`) y Codex
  (`.agents/skills/oc*`) se generan desde una sola fuente (`agents/*.md` +
  `skills/oc/`) mediante `python3 scripts/sync_agents.py`.

Prueba de humo rápida sin conexión (sustituye `demo.mp4` por cualquier clip corto tuyo):

```bash
oc --project out/demo ingest --input demo.mp4 --max-seconds 60
oc --project out/demo stt --chunk 0 --mock
oc --project out/demo transcript-merge
oc --project out/demo status
```

Consulta `docs/HARNESS.md` para el diseño completo.

## Costo (ejecuciones reales)

Cálculos aproximados con los precios de lista de OpenAI — una charla de 110 minutos de principio a fin (STT completo,
5 shorts con subtítulos incrustados, 2 candidatos de formato largo, miniaturas) ronda los
**$1**: whisper-1 ≈ $0.006/min de audio (~$0.66 por 110 min), gpt-image-2
≈ $0.03-0.07 por miniatura generada (las miniaturas de captura de fotograma son gratis),
la traducción de subtítulos con gpt-4o-mini cuesta fracciones de centavo por clip. Las ejecuciones con `--mock`
cuestan $0, y el registro de reanudación nunca vuelve a facturar STT/renders ya completados.

## Estado

OpenClip es software en etapa temprana. Es utilizable localmente, pero las APIs, los esquemas de salida y los formatos de los paquetes de revisión pueden cambiar antes de una versión estable.

## Requisitos

- Python 3.11+
- `uv`
- `ffmpeg` y `ffprobe`
- Clave de API de OpenAI para ejecuciones reales

Las ejecuciones mock no llaman a APIs externas y son útiles para el desarrollo.

## Instalación

Requisitos previos para todos los modos: `ffmpeg`/`ffprobe` en el PATH, Python 3.11+ y una
`OPENAI_API_KEY` para ejecuciones reales (las ejecuciones mock no necesitan clave).

### A. Un comando, cualquier agente (recomendado)

Instala la skill del orquestador + las 12 skills de trabajadores en Claude Code y
Codex (probado), además de Cursor y [cualquier agente del protocolo de skills](https://github.com/vercel-labs/skills):

```bash
npx skills add Q00/openclip
```

Luego instala la CLI `oc` una vez (la skill también se autocomprueba y lo ofrece en
el primer uso):

```bash
uv tool install "git+https://github.com/Q00/openclip@v0.1.0"
```

Esto instala código desde el repositorio — fija una etiqueta de release (mostrada) y consulta
las [notas de la versión](https://github.com/Q00/openclip/releases) en entornos
sensibles.

Abre tu agente y di *"haz shorts de este video"* (funciona cualquier idioma),
o invoca la skill `oc` directamente. La
carpeta de la skill incluye los manifiestos de flujo y la referencia de herramientas, así que funciona fuera
del repo.

### B. Plugin de Claude Code (añade subagentes + el hook de evidencia)

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

El plugin registra los tipos de subagente `oc-*` y la puerta de evidencia `SubagentStop`
(las instalaciones solo de skills ejecutan los trabajadores como subagentes de propósito general sin el
hook). La CLI `oc` sigue viniendo del `uv tool install` de arriba.

**Codex — habilitar la puerta de evidencia.** Las skills se instalan mediante el modo A; para obtener también
la puerta de "hecho sin evidencia" en tu propio proyecto, copia los dos archivos de configuración
de este repo y mantén válida la ruta del script del hook:

```bash
mkdir -p .codex hooks
curl -fsSLo .codex/config.toml  https://raw.githubusercontent.com/Q00/openclip/main/.codex/config.toml
curl -fsSLo .codex/hooks.json   https://raw.githubusercontent.com/Q00/openclip/main/.codex/hooks.json
curl -fsSLo hooks/verify_evidence_hook.py https://raw.githubusercontent.com/Q00/openclip/main/hooks/verify_evidence_hook.py
```

`config.toml` establece `features.hooks = true` (requerido para que Codex cargue
`hooks.json`); el hook se resuelve mediante `${CODEX_PROJECT_DIR:-$PWD}`.

### C. Clon del repo (desarrollo)

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

Abre Claude Code o Codex en la raíz del repo — los agentes, skills, comandos y hooks
se cargan automáticamente.

Para ejecuciones reales de OpenAI, establece una clave de API en tu shell:

```bash
export OPENAI_API_KEY="..."
```

También puedes copiar `.env.example` a `.env` para desarrollo local. Nunca subas claves reales al repositorio.

## Inicio rápido — pipeline heredado de una sola ejecución

> **Solo clon del repo (modo C).** Este es el pipeline fijo original que precede
> al harness de agentes; el harness de arriba es la ruta recomendada. Tras
> `uv tool install`, usa `openclip run ...` directamente en lugar de `uv run`.

Ejecuta con los servicios reales de OpenAI:

```bash
uv run openclip run /path/to/input.mp4 --out ./out --strategy-approved
```

Genera todos los candidatos viables de short y de formato largo e incrusta subtítulos en coreano en los shorts:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --strategy-approved \
  --all-short-candidates \
  --all-long-candidates \
  --burn-short-ko-subtitles
```

Ejecuta una prueba de humo local acotada sin llamadas de red:

```bash
uv run openclip run /path/to/input.mp4 \
  --out ./out \
  --mock-openai \
  --max-source-seconds 660 \
  --shorts 1 \
  --long-candidates 1 \
  --strategy-approved
```

## Salidas

OpenClip escribe cada ejecución bajo:

```text
OUT_DIR/{input_basename}/
```

Las salidas típicas incluyen:

- `shorts/*.mp4`
- `long/*.mp4`
- `edited/edited_original.mp4`
- `*.en.srt`, `*.ko.srt`, `*.es.srt`, `*.ja.srt`, `*.zh-Hans.srt`
- `*.thumbnail.png`
- `manifest.json`
- `analysis/candidate_selection.json`
- `analysis/edl.json`
- `analysis/takes_packed.md`
- `analysis/playback_checks/*`
- `analysis/subagent_packets/*`

Los medios generados, los videos fuente locales, `.env`, los entornos virtuales, las cachés y `out/` son ignorados por git. Mantén las salidas renderizadas fuera de los commits.

## Verificación — pipeline heredado (solo clon del repo)

> Estos scripts vienen en el árbol del repo, no en el paquete instalado. Las ejecuciones del harness
> se verifican de otra forma: `oc verify` + el agente `oc-verifier` (consulta
> `docs/HARNESS.md`).

Valida una ejecución existente:

```bash
python3 codex/skills/openclip/scripts/verify_run_artifacts.py \
  ./out/example/input_basename
```

Ejecuta una puerta paralela de reproducción/decodificación:

```bash
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename \
  --workers 6 \
  --full-decode \
  --write-manifest
```

Regenera los paquetes de revisión de subagentes de Codex para una ejecución existente:

```bash
python3 codex/skills/openclip/scripts/build_subagent_packets.py \
  ./out/example/input_basename
```

## Flujo de revisión — pipeline heredado

El pipeline heredado de OpenClip crea paquetes autocontenidos de subagentes de Codex bajo `analysis/subagent_packets/`.

El grafo de revisión es:

1. `collect`: los editores de shorts y de formato largo reúnen afirmaciones de contenido independientes.
2. `verify`: las puertas de continuidad, reproducción y artefactos comprueban archivos y manifiestos.
3. `design`: el director de miniaturas comprueba la coincidencia del prompt y la imagen.
4. `adversarial`: el crítico de retención busca el probable abandono del espectador.
5. `synthesize`: el revisor de la puerta final aprueba solo después de que cada vía tenga evidencia.

Los resultados `PASS` de los subagentes se tratan como afirmaciones, no como pruebas. El hilo raíz o el proceso de release debe verificar las rutas citadas, los manifiestos y la evidencia de reproducción antes de publicar las salidas.

## Desarrollo

```bash
uv sync --extra dev
uv run pytest
python3 -m compileall -q src codex/skills/openclip/scripts tests
```

Antes de abrir un PR o publicar una rama, ejecuta un escaneo de secretos:

```bash
rg -n -e "[s]k-proj-" -e "OPENAI_API_KEY\\s*=\\s*[s]k-" -e "OPEN_API_KEY\\s*=\\s*[s]k-" \
  --glob '!out/**' \
  --glob '!.env' \
  --glob '!demo.mp4' \
  --glob '!lecturer/**' \
  --glob '!.venv/**' .
```

## Seguridad y privacidad

OpenClip procesa medios locales y puede enviar audio, texto de transcripción, texto de subtítulos y prompts/fotogramas de referencia de miniaturas a OpenAI cuando no se usa `--mock-openai`.

No ejecutes el modo de proveedor real sobre medios privados, regulados o de terceros a menos que tengas el derecho de procesarlos con los proveedores configurados. Usa `--mock-openai` para pruebas locales que deban evitar llamadas de red.

## Licencia

MIT. Consulta [LICENSE](LICENSE).
