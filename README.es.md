<div align="center">

![OpenClip — el harness de edición de video orquestado por agentes](docs/assets/banner.jpg)

### Tú diriges. Una flota de agentes en paralelo debate los cortes, renderiza y demuestra cada entregable — shorts, formato largo, subtítulos y miniaturas a partir de un único video largo.

*Python entrega las herramientas, los agentes entregan el criterio, el humano aporta el buen gusto.*

[![Release](https://img.shields.io/github/v/release/Q00/openclip)](https://github.com/Q00/openclip/releases)
[![PyPI](https://img.shields.io/pypi/v/openclip-agent?label=pypi)](https://pypi.org/project/openclip-agent/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![Agent Skills](https://img.shields.io/badge/npx%20skills%20add-Q00%2Fopenclip-111)](https://github.com/vercel-labs/skills)

```bash
npx skills add Q00/openclip && uv tool install openclip-agent
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

## Primeros pasos — tu primera ejecución

Después de instalar (más abajo), no ejecutas un pipeline — hablas con tu agente.

**1. Abre tu agente** (Claude Code o Codex) en una carpeta con tu video.

**2. Di lo que quieres**, en cualquier idioma:

```
tú     haz shorts de ./talk.mp4

agente Leyendo flow2-shorts. Divido el audio en fragmentos y despliego
       workers de STT en paralelo… transcripción combinada (110 min).
       Buscando ganchos en las secciones — 6 candidatos clasificados.
       Voy a cortar los 3 mejores como shorts 9:16 con subtítulos
       incrustados y una miniatura cada uno. ¿Apruebas la lista de
       ganchos antes de renderizar?  [tú: sí, descarta el #4]
       Renderizando… cada clip superó la puerta de evidencia (duración,
       aspecto, audio, sincronía de subtítulos). Listo — mira
       out/talk/shorts/.
```

El orquestador se detiene a consultar en los puntos de decisión reales (qué
ganchos, qué cortes, qué miniatura) y bloquea cualquier "hecho" que no tenga
evidencia detrás.

**3. Recoge las salidas.** Todo aparece bajo el directorio de tu proyecto
(aquí `out/talk/`):

| Carpeta | Qué contiene |
| --- | --- |
| `shorts/` | clips `.mp4` verticales con subtítulos incrustados |
| `thumbnails/` | una miniatura diseñada por cada entregable |
| `subs/` | archivos `.srt` complementarios (por idioma) |
| `evidence/` | el JSON de prueba del verificador para cada render |

**Costo:** una charla completa de 110 minutos (STT + varios shorts + miniaturas)
cuesta alrededor de **$1** según los precios de lista de OpenAI. Añade `--mock`
en cualquier parte y cuesta **$0** — ideal para una primera prueba sin conexión
(consulta [Costo](#costo) para el desglose).

### ¿Prefieres la CLI, sin agente?

Cada paso que dan los agentes es un simple comando `oc`. Esta secuencia no
necesita clave de API y no cuesta nada — el STT se ejecuta en `--mock`, y el
corte y la miniatura son trabajo local de ffmpeg (sin llamada a OpenAI):

```bash
oc --project out/talk ingest --input talk.mp4 --max-seconds 120
oc --project out/talk stt --chunk 0 --mock
oc --project out/talk transcript-merge
oc --project out/talk clip --input talk.mp4 --start 30 --end 75 --aspect 9:16 --id s1
oc --project out/talk thumbnail --input talk.mp4 --start 30 --end 75 --title "The one trick"
oc --project out/talk status
```

¿Tienes una foto del ponente? Sustituye la línea de la miniatura por el
recorte diseñado sin IA — sigue siendo gratis, sigue siendo sin conexión tras
una descarga única del modelo:
`… thumbnail --composite --persona speaker.jpg --style editorial --title "…"`.

`oc --help` es la lista de comandos canónica. Consulta
[`skills/oc/tools-reference.md`](skills/oc/tools-reference.md) para cada verbo.

## Qué produce

- **shorts verticales** de 30-60 segundos con subtítulos incrustados y sincronizados palabra por palabra
- **candidatos de formato largo** de 8-12 minutos que terminan en una conclusión, no a mitad de frase
- un **original con cortes editados** (silencio/muletillas/repetición debatidos y eliminados, no solo detectados)
- **subtítulos SRT** para `en`, `ko`, `es`, `ja`, `zh-Hans`
- **miniaturas diseñadas** — la identidad real del ponente se preserva mediante
  `--persona`, ajustes `--style` seleccionados, un recorte `--composite` sin
  IA y sin costo, o un render de gpt-image; el harness aprende el gusto de tu
  canal a lo largo de las rondas (`oc taste`)
- un manifiesto, EDL, archivos de evidencia y un registro reanudable para cada ejecución

**Míralo, no te fíes de nuestra palabra:** [docs/examples/](docs/examples/) contiene
artefactos reales de una ejecución de 109 minutos — un fotograma de short subtitulado, una miniatura, el
fragmento de transcripción detrás de un gancho, el SRT, el JSON de evidencia 10/10 y el
registro de reanudación.

## Instalación

Requisitos previos para todos los modos: `ffmpeg`/`ffprobe` en el PATH, Python 3.11+ y una
`OPENAI_API_KEY` para ejecuciones reales (las ejecuciones mock no necesitan clave).

**¿Qué instalación quieres?**

| Tú eres… | Instalación | Obtienes |
| --- | --- | --- |
| un usuario de **Claude Code** | plugin (B) | los tipos de subagente + el hook de la puerta de evidencia |
| de **Codex / Cursor / otro agente con protocolo de skills** | `npx skills add` (A) | el orquestador + las skills de trabajadores |
| **solo la CLI** (sin agente) | PyPI (`uv tool install`) | únicamente el comando `oc` |

Las tres se pueden combinar — las skills/el plugin incluyen los agentes, la
CLI entrega las herramientas `oc` que estos invocan.

### A. Catálogo de skills, cualquier agente (recomendado)

Para Codex, Cursor y [cualquier agente del protocolo de skills](https://github.com/vercel-labs/skills).
Instala el orquestador más todas las skills de trabajadores:

```bash
npx skills add Q00/openclip
```

Luego instala la CLI `oc` una vez (la skill se autocomprueba y lo ofrece en
el primer uso):

```bash
uv tool install openclip-agent      # or: pip install openclip-agent
```

Abre tu agente y di *"haz shorts de este video"* (funciona en cualquier
idioma), o invoca la skill `oc` directamente. La carpeta de la skill incluye
los manifiestos de flujo y la referencia de herramientas, así que funciona
fuera del repo.

### B. Plugin de Claude Code (añade subagentes + el hook de evidencia)

Para usuarios de Claude Code. Registra los tipos de subagente `oc-*` y la
puerta de evidencia `SubagentStop` (las instalaciones solo de skills ejecutan
los trabajadores como subagentes de propósito general sin el hook):

```
/plugin marketplace add Q00/openclip
/plugin install openclip@openclip
```

La CLI `oc` sigue viniendo del `uv tool install openclip-agent` de arriba.

**Codex — habilitar la puerta de evidencia.** Las skills se instalan mediante
el modo A; para obtener también la puerta de "hecho sin evidencia" en tu
propio proyecto, copia los dos archivos de configuración de este repo y
mantén válida la ruta del script del hook:

```bash
mkdir -p .codex hooks
curl -fsSLo .codex/config.toml  https://raw.githubusercontent.com/Q00/openclip/main/.codex/config.toml
curl -fsSLo .codex/hooks.json   https://raw.githubusercontent.com/Q00/openclip/main/.codex/hooks.json
curl -fsSLo hooks/verify_evidence_hook.py https://raw.githubusercontent.com/Q00/openclip/main/hooks/verify_evidence_hook.py
```

`config.toml` establece `features.hooks = true` (requerido para que Codex
cargue `hooks.json`); el hook se resuelve mediante `${CODEX_PROJECT_DIR:-$PWD}`.

### C. Solo la CLI (PyPI)

Si solo quieres las herramientas `oc`/`openclip` sin agente:

```bash
uv tool install openclip-agent      # or: pip install openclip-agent
```

### D. Clon del repo (desarrollo)

```bash
git clone https://github.com/Q00/openclip && cd openclip
uv sync --extra dev
```

Abre Claude Code o Codex en la raíz del repo — los agentes, skills, comandos
y hooks se cargan automáticamente. Para ejecuciones reales de OpenAI,
establece una clave en tu shell (o copia `.env.example` a `.env`; nunca subas
claves reales):

```bash
export OPENAI_API_KEY="..."
```

## Harness de agentes (`oc`)

En lugar de un flujo de trabajo fijo, un agente orquestador lee un manifiesto
de flujo y despliega subagentes trabajadores en paralelo mientras el humano
guía cada decisión creativa. Trece definiciones de rol viven en
[`agents/`](agents/): un orquestador más doce trabajadores especializados.

Cuatro flujos:

1. **`flows/flow1-cutedit.yaml`** — proxy LRF/LRV → STT en paralelo → un **debate de edición de cortes** (los proponentes argumentan a través de las lentes de muletillas/ritmo/narrativa, un juez las reconcilia) → original con cortes editados + subtítulos.
2. **`flows/flow2-shorts.yaml`** — un video largo → STT en paralelo → minería de ganchos → shorts 9:16 subtitulados + miniaturas.
3. **`flows/flow3-assemble.yaml`** — teje N videos en un único formato largo, luego extrae sus ganchos en shorts (cada uno con subtítulos + una miniatura).
4. **`flows/flow4-thumbnail.yaml`** — miniaturas emparejadas con cada gancho: un fotograma con un titular incrustado, y/o un render de gpt-image impulsado por el subtítulo del gancho.

Piezas clave:

- **Herramientas:** `oc --project <DIR> <cmd>` — `proxy, ingest, stt, transcript-merge,
  probe, cut, clip, subtitle, thumbnail, burn-srt, concat, verify, status,
  resume, steer, steer-resolve, toolbox, taste, acp`. Cada una imprime una línea JSON;
  `oc --help` es la referencia canónica. Consulta `skills/oc/tools-reference.md`.
- **Guía humana:** `oc steer --note "..." --scope "global | <stage> | section:<a>-<b> | <deliverable_id>"`.
  El orquestador lee las directivas abiertas de `oc status` antes de cada oleada y
  las inyecta en los trabajadores. El director siempre está en el bucle.
- **Puerta de evidencia:** un `oc-verifier` independiente comprueba cada render frente a
  la evidencia observable y las clases de fallo adversariales; solo un veredicto `confirmed`
  avanza. Un hook `SubagentStop` bloquea el "hecho sin evidencia".
- **Runtime dual:** Claude Code (`.claude/agents`, `.claude/skills/oc`) y Codex
  (`.agents/skills/oc*`) se generan desde una sola fuente (`agents/*.md` +
  `skills/oc/`) mediante `python3 scripts/sync_agents.py`.

Para una prueba de humo rápida sin conexión que puedas ejecutar, consulta la
[secuencia de la CLI](#prefieres-la-cli-sin-agente) más arriba; `docs/HARNESS.md`
tiene el diseño completo.

### Novedades en v0.2: miniaturas diseñadas + gusto aprendido

**Las miniaturas diseñadas** (`oc thumbnail`) se ven dirigidas artísticamente,
no como una simple captura de fotograma: `--persona <photo|dir>` preserva la
**identidad real del ponente** (edición con gpt-image); `--style
clean|editorial|bold|keynote` elige un ajuste preestablecido y seleccionado;
`--composite` es la **ruta sin IA** (recorte con rembg sobre un fondo de
estudio con un titular tipografiado — cero píxeles generados, **costo
cero**, instantáneo); `--render-text` deja que gpt-image-2 tipografíe el
titular por sí mismo (probabilístico — el contrato verifica la ortografía en
cada render); `--prompt-note "..."` añade dirección artística por render.

**`oc taste`** (`show|note|evolve|revert`) es un **bucle de
personalización** — el harness aprende el estilo visual de tu canal. Tú
registras veredictos sobre las miniaturas renderizadas (`taste note`); un
agente los refleja en la **siguiente generación de guía** (`taste evolve`)
con marcadores por generación, linaje y reversión (`taste revert`) cuando una
generación más nueva puntúa peor. La guía se mantiene por dominio; el
almacenamiento resuelve `$OPENCLIP_HOME` → el `toolbox/` del repo (opt-in de
equipo) → `~/.openclip` (por defecto del plugin).

## Costo

Cálculos aproximados con los precios de lista de OpenAI — una charla de 110
minutos de principio a fin (STT completo, 5 shorts con subtítulos
incrustados, 2 candidatos de formato largo, miniaturas) ronda los **$1**:
whisper-1 ≈ $0.006/min de audio (~$0.66 por 110 min), gpt-image-2 ≈
$0.03-0.07 por miniatura generada (las miniaturas de captura de fotograma y
`--composite` son gratis), la traducción de subtítulos con gpt-4o-mini cuesta
fracciones de centavo por clip. Las ejecuciones con `--mock` cuestan $0, y el
registro de reanudación nunca vuelve a facturar STT/renders ya completados.

## Requisitos y estado

- Python 3.11+, `uv`, y `ffmpeg`/`ffprobe` en el PATH
- Clave de API de OpenAI para ejecuciones reales (las ejecuciones mock no llaman a ninguna API externa)

OpenClip es software en etapa temprana. Es utilizable localmente, pero las
APIs, los esquemas de salida y los formatos de los paquetes de revisión
pueden cambiar antes de una versión estable.

## Solución de problemas

- **`ffmpeg`/`ffprobe: command not found`** — instala ffmpeg y asegúrate de
  que ambos binarios estén en tu `PATH` (`ffmpeg -version` debería imprimir
  algo). Cada ruta de render los invoca.
- **Falta `OPENAI_API_KEY`** — configúrala para ejecuciones reales
  (`export OPENAI_API_KEY=...`). No la necesitas para `--mock`: el modo mock
  no hace llamadas de red.
- **`OPENAI_BASE_URL` debe estar sin definir para ejecuciones reales** — una
  base URL de CLI-proxy rompe las llamadas a Whisper y a imágenes. Desactívala
  (`unset OPENAI_BASE_URL`) antes de una ejecución real.
- **La primera ejecución de `--composite` se pausa** — descarga una vez el
  modelo de eliminación de fondo rembg, y luego funciona completamente sin
  conexión. Necesita `uvx` (de `uv`) en el PATH.
- **Una ejecución real "tiene éxito" pero falta un archivo** — eso no puede
  publicarse: la puerta de evidencia solo avanza con un veredicto `confirmed`.
  Revisa el `evidence/*.json` del entregable que falló.

<details>
<summary><strong>Pipeline heredado de una sola ejecución (<code>openclip run</code>)</strong> — el pipeline fijo original, aún compatible</summary>

> **Solo clon del repo (modo D).** Este es el pipeline fijo original que
> precede al harness de agentes; el harness de arriba es la ruta
> recomendada. Tras `uv tool install`, usa `openclip run ...` directamente en
> lugar de `uv run`.

### Inicio rápido

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

### Salidas

Cada ejecución escribe bajo `OUT_DIR/{input_basename}/`. Las salidas típicas
incluyen `shorts/*.mp4`, `long/*.mp4`, `edited/edited_original.mp4`, SRTs por
idioma (`*.en.srt`, `*.ko.srt`, `*.es.srt`, `*.ja.srt`, `*.zh-Hans.srt`),
`*.thumbnail.png`, `manifest.json`, y `analysis/` (candidate_selection.json,
edl.json, takes_packed.md, playback_checks/, subagent_packets/). Los medios
generados, las fuentes locales, `.env`, los entornos virtuales, las cachés y
`out/` están en gitignore.

### Verificación

Estos scripts vienen en el árbol del repo, no en el paquete instalado. Las
ejecuciones del harness se verifican de otra forma: `oc verify` + el agente
`oc-verifier` (consulta `docs/HARNESS.md`).

```bash
# validate an existing run
python3 codex/skills/openclip/scripts/verify_run_artifacts.py ./out/example/input_basename

# parallel playback/decode gate
python3 codex/skills/openclip/scripts/parallel_video_playback_check.py \
  ./out/example/input_basename --workers 6 --full-decode --write-manifest

# regenerate Codex subagent review packets
python3 codex/skills/openclip/scripts/build_subagent_packets.py ./out/example/input_basename
```

### Flujo de revisión

El pipeline heredado crea paquetes autocontenidos de subagentes de Codex bajo
`analysis/subagent_packets/`. El grafo de revisión es: `collect` (los
editores reúnen afirmaciones de contenido independientes) → `verify` (las
puertas de continuidad/reproducción/artefactos) → `design` (ajuste de la
miniatura) → `adversarial` (crítico de retención) → `synthesize` (la puerta
final aprueba solo después de que cada vía tenga evidencia). Los resultados
`PASS` de los subagentes son afirmaciones, no pruebas — el hilo raíz o el
proceso de release debe verificar las rutas citadas, los manifiestos y la
evidencia de reproducción antes de publicar.

</details>

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

OpenClip procesa medios locales y puede enviar audio, texto de transcripción,
texto de subtítulos y prompts/fotogramas de referencia de miniaturas
(incluidas fotos de persona) a OpenAI cuando no se usa `--mock`. No ejecutes
el modo de proveedor real sobre medios privados, regulados o de terceros a
menos que tengas el derecho de procesarlos con los proveedores configurados.
Usa `--mock` para pruebas locales que deban evitar llamadas de red.

## Licencia

MIT. Consulta [LICENSE](LICENSE).
