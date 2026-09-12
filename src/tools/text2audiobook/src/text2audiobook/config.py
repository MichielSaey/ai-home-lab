"""JSON configuration: dataclasses + load_config() with a baked-in default path."""

import json
import logging
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TOOL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _TOOL_ROOT / "config.json"
BOOKS_CONFIG_DIRNAME = "config.books"
EXPERIMENT_CONFIG_PATH = _TOOL_ROOT.parent / "epub-to-audiobook/config.json"

DEFAULT_CLEAN_PROMPT = (
    "Clean this text for text-to-speech narration. Return only the cleaned text, "
    "no commentary.\n\n"
    "Rules:\n"
    "- Remove URLs.\n"
    "- Spell dates like 03/09/2026 as \"the third of September, twenty twenty-six\".\n"
    "- Expand i.e. and e.i. to \"in other words\", and e.g. to \"for example\".\n"
    "- Delete bibliography, references, works cited, and endnotes sections entirely.\n"
    "- Citations for listening: never read page numbers, translators, publishers, "
    "cities, or stacked \"see also\" lists. When a source is woven into the sentence, "
    "keep one short spoken credit (author and work title only). Example: "
    "\"(M. Eliade, Rites and Symbols of Initiation, tr. W.R. Trask "
    "[New York: Harper Colophon, 1958], 53–58; see also C. Kerslake, …)\" becomes "
    "\"(Eliade in Rites and Symbols of Initiation)\". "
    "Example: \"Mark Fisher (2012). Terminator vs Avatar in #Accelerate: The "
    "Accelerationist Reader, Urbanomic, p. 342.\" becomes "
    "\"Wrote Mark Fisher in twenty twelve.\". "
    "If a parenthesis or clause is only a citation dump and not needed for the "
    "spoken argument, delete it.\n"
    "- Remove editorial ellipses in brackets such as [...] or […].\n"
    "- Do not read tables or figures cell by cell. Replace them with a short "
    "reference to the ebook or the original page.\n"
    "- Speak section marks: §0.21 becomes \"section 0.21\".\n"
    "- Title lists in parentheses such as (Cyberpunk, Elysium) become "
    "\"for example Cyberpunk, Elysium\".\n"
    "- Drop leading # from tags (#Accelerate → Accelerate); expand & to and "
    "and % to percent.\n"
    "- Improve phonetic readability otherwise.\n\n"
    "Text:\n{text}"
)

DEFAULT_DIRECTION_PROMPT = (
    "Write a short delivery instruction (1–2 sentences, English) for Qwen3-TTS "
    "instruct for the narration chunk below. Return only the instruction — no "
    "spoken narration text, no commentary, and no bracket tags like [excited].\n\n"
    "Rules:\n"
    "- Add only passage-level pace, emotion, and emphasis for this chunk.\n"
    "- Do not invent a different accent, language, or speaker persona; the "
    "global TTS instruct already sets a native English female audiobook narrator.\n"
    "- Stay restrained for audiobook narration; avoid theatrical overacting.\n"
    "- If the passage is neutral exposition, say so briefly (calm steady pace).\n\n"
    "Narration:\n{text}"
)

DEFAULT_TTS_INSTRUCT = (
    "Young adult woman with a warm, gentle mid pitch. Speak with native American "
    "or neutral US English pronunciation — clear native English vowels, consonants, "
    "and rhythms. Do not use a Chinese, Mandarin, or any non-English accent. "
    "Deliver at a slow, steady, restrained audiobook pace suited to dense "
    "nonfiction, remaining calm, precise, and easy to follow."
)


@dataclass
class PathsConfig:
    input_dir: Path = Path("data/input")
    staging_dir: Path = Path("data/staging")
    output_dir: Path = Path("data/output")
    runs_dir: Path = Path("data/runs")

    def resolve_against(self, base: Path) -> None:
        """Resolve relative paths against the config file's directory."""
        for name in ("input_dir", "staging_dir", "output_dir", "runs_dir"):
            value = Path(getattr(self, name))
            if not value.is_absolute():
                value = base / value
            setattr(self, name, value)


@dataclass
class ChunkingConfig:
    format_words_per_chunk: int = 1000
    speak_target_chars: int = 800
    speak_max_chars: int = 1200
    max_chunks_per_chapter: int | None = None


@dataclass
class SelectionConfig:
    keep_chapter_indices: list[int] | None = None
    max_chapters: int | None = None
    include_intro: bool = True
    include_appendix: bool = False
    opening_words: int = 250
    opening_batch_size: int = 4


@dataclass
class LlmConfig:
    model_id: str = "Qwen/Qwen2.5-7B-Instruct"
    device: str = "cuda"
    cleanup: bool = True
    direction: bool = True
    cleanup_batch_size: int = 1
    max_new_tokens: int = 2048
    direction_max_new_tokens: int = 128
    clean_prompt: str = DEFAULT_CLEAN_PROMPT
    direction_prompt: str = DEFAULT_DIRECTION_PROMPT


@dataclass
class TtsConfig:
    model_id: str = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
    lang: str = "English"
    voice: str = "Serena"
    device: str = "auto"
    ref_audio: str | None = None
    ref_text: str | None = None
    x_vector_only: bool = False
    instruct: str | None = DEFAULT_TTS_INSTRUCT
    batch_max_chars: int = 0
    # VRAM budget for n * (max(lens) + batch_vram_overhead); calibrated via --calibrate-tts-batch.
    # Production default is below clean-GPU frontiers to leave mid-run fragmentation headroom.
    batch_max_pad_chars: int = 2200
    batch_vram_overhead: int = 0
    # Hard ceiling for short units; pad budget limits long ones.
    batch_max_items: int = 16


def resolve_ref_audio(
    ref_audio: str | None,
    *,
    config_path: Path | None,
) -> Path | None:
    """Resolve ``tts.ref_audio`` against the config file directory when relative."""
    if ref_audio is None:
        return None
    stripped = str(ref_audio).strip()
    if not stripped:
        return None
    path = Path(stripped)
    if not path.is_absolute() and config_path is not None:
        path = config_path.parent / path
    return path


@dataclass
class OutputConfig:
    chapter_mp3: bool = False
    mp3_bitrate: str = "128k"
    m4b_bitrate: str = "128k"
    keep_wav: bool = False
    skip_existing: bool = True
    chunk_silence_ms: int = 300
    chapter_silence_ms: int = 1000
    loudnorm: bool = True
    speak_footnote_cues: bool = False


@dataclass
class PipelineConfig:
    concurrent_models: bool = False
    ffmpeg_workers: int = 2
    queue_size: int = 32


@dataclass
class AppConfig:
    paths: PathsConfig
    chunking: ChunkingConfig
    selection: SelectionConfig
    llm: LlmConfig
    tts: TtsConfig
    output: OutputConfig
    pipeline: PipelineConfig
    config_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable snapshot for run manifests."""
        return _jsonable(asdict(self))


_SECTIONS: dict[str, type] = {
    "paths": PathsConfig,
    "chunking": ChunkingConfig,
    "selection": SelectionConfig,
    "llm": LlmConfig,
    "tts": TtsConfig,
    "output": OutputConfig,
    "pipeline": PipelineConfig,
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge overlay onto a copy of base (overlay wins)."""
    result = deepcopy(base)
    for key, value in overlay.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _build_section(cls: type, data: Any, section: str) -> Any:
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ValueError(f"Config section '{section}' must be a JSON object")
    known = {f.name for f in fields(cls)}
    for key in sorted(set(data) - known):
        logger.warning("Ignoring unknown config key: %s.%s", section, key)
    return cls(**{key: value for key, value in data.items() if key in known})


def _normalize_raw_config(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    paths_data = normalized.get("paths")
    if isinstance(paths_data, dict):
        paths_data = dict(paths_data)
        if "input_dir" not in paths_data and "epub_dir" in paths_data:
            paths_data["input_dir"] = paths_data["epub_dir"]
        paths_data.pop("epub_dir", None)
        normalized["paths"] = paths_data

    chunking_data = normalized.get("chunking")
    if isinstance(chunking_data, dict):
        chunking_data = dict(chunking_data)
        if "format_words_per_chunk" not in chunking_data and "words_per_chunk" in chunking_data:
            chunking_data["format_words_per_chunk"] = chunking_data["words_per_chunk"]
        chunking_data.pop("words_per_chunk", None)
        if "speak_target_phonemes" in chunking_data or "speak_max_phonemes" in chunking_data:
            logger.warning(
                "chunking.speak_*_phonemes is obsolete (Qwen3-TTS uses character "
                "budgets); ignoring old keys — set speak_target_chars / speak_max_chars"
            )
            chunking_data.pop("speak_target_phonemes", None)
            chunking_data.pop("speak_max_phonemes", None)
        normalized["chunking"] = chunking_data

    tts_data = normalized.get("tts")
    if isinstance(tts_data, dict):
        tts_data = dict(tts_data)
        if "speed" in tts_data:
            logger.warning(
                "tts.speed is ignored (Qwen3-TTS); "
                "use tts.instruct for style/rate hints"
            )
            tts_data.pop("speed", None)
        if "lang" in tts_data:
            tts_data["lang"] = _normalize_tts_lang(tts_data["lang"])
        if "voice" in tts_data:
            tts_data["voice"] = _normalize_tts_voice(tts_data["voice"])
        normalized["tts"] = tts_data
    return normalized


# Kokoro single-letter codes → Qwen3-TTS language names.
# Unsupported codes (e.g. Hindi "h") fall back to English with a warning.
_KOKORO_LANG_TO_QWEN: dict[str, str] = {
    "a": "English",  # American
    "b": "English",  # British
    "e": "Spanish",
    "f": "French",
    "h": "English",  # Hindi — not in Qwen3-TTS language set
    "i": "Italian",
    "j": "Japanese",
    "p": "Portuguese",
    "z": "Chinese",
}

# First letter of Kokoro voice ids → approximate Qwen CustomVoice speaker.
_KOKORO_VOICE_PREFIX_TO_QWEN: dict[str, str] = {
    "af": "Serena",  # American female → warm female (can speak English)
    "am": "Ryan",
    "bf": "Serena",
    "bm": "Ryan",
    "ff": "Serena",
    "jf": "Ono_Anna",
    "jm": "Ono_Anna",
    "zf": "Vivian",
    "zm": "Uncle_Fu",
}


def _normalize_tts_lang(lang: Any) -> Any:
    if not isinstance(lang, str):
        return lang
    stripped = lang.strip()
    if not stripped:
        return lang
    mapped = _KOKORO_LANG_TO_QWEN.get(stripped.lower())
    if mapped is not None:
        logger.warning(
            "tts.lang %r is a legacy Kokoro code; mapping to %r for Qwen3-TTS",
            stripped,
            mapped,
        )
        return mapped
    return stripped


def _normalize_tts_voice(voice: Any) -> Any:
    if not isinstance(voice, str):
        return voice
    stripped = voice.strip()
    if not stripped:
        return voice
    # Already a Qwen speaker (case-insensitive); leave for resolve_voice to canonicalize.
    from text2audiobook.voices import get_voice

    if get_voice(stripped) is not None:
        return stripped
    # Kokoro ids look like af_bella / bm_george.
    prefix = stripped.lower().split("_", 1)[0]
    mapped = _KOKORO_VOICE_PREFIX_TO_QWEN.get(prefix)
    if mapped is not None:
        logger.warning(
            "tts.voice %r is a legacy Kokoro id; mapping to %r for Qwen3-TTS",
            stripped,
            mapped,
        )
        return mapped
    return stripped


def app_config_from_dict(
    data: dict[str, Any],
    *,
    config_path: Path | None = None,
) -> AppConfig:
    """Build AppConfig from a raw JSON object."""
    if not isinstance(data, dict):
        raise ValueError("Config root must be a JSON object")

    for key in sorted(set(data) - set(_SECTIONS)):
        logger.warning("Ignoring unknown config section: %s", key)

    data = _normalize_raw_config(data)
    paths = _build_section(PathsConfig, data.get("paths"), "paths")
    if config_path is not None:
        paths.resolve_against(config_path.parent)

    tts = _build_section(TtsConfig, data.get("tts"), "tts")
    resolved_ref = resolve_ref_audio(tts.ref_audio, config_path=config_path)
    if resolved_ref is not None:
        tts = replace(tts, ref_audio=str(resolved_ref))

    return AppConfig(
        paths=paths,
        chunking=_build_section(ChunkingConfig, data.get("chunking"), "chunking"),
        selection=_build_section(SelectionConfig, data.get("selection"), "selection"),
        llm=_build_section(LlmConfig, data.get("llm"), "llm"),
        tts=tts,
        output=_build_section(OutputConfig, data.get("output"), "output"),
        pipeline=_build_section(PipelineConfig, data.get("pipeline"), "pipeline"),
        config_path=config_path,
    )


def load_config(path: Path | None = None) -> AppConfig:
    """Load an AppConfig from a JSON file (default: the shipped tool config)."""
    config_path = (Path(path) if path is not None else DEFAULT_CONFIG_PATH).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a JSON object: {config_path}")
    return app_config_from_dict(data, config_path=config_path)


def book_config_path(base: AppConfig, slug: str) -> Path | None:
    """Path to ``config.books/<slug>.json`` next to the base config, if any."""
    if base.config_path is None:
        return None
    return base.config_path.parent / BOOKS_CONFIG_DIRNAME / f"{slug}.json"


def resolve_book_config(base: AppConfig, slug: str) -> AppConfig:
    """Deep-merge ``config.books/<slug>.json`` onto base when the file exists.

    Book overlays may not redefine ``paths`` (kept from the base/default).
    """
    path = book_config_path(base, slug)
    if path is None or not path.exists():
        return base

    overlay = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(overlay, dict):
        raise ValueError(f"Book config root must be a JSON object: {path}")
    if "paths" in overlay:
        logger.info(
            "Ignoring paths in book overlay %s (paths come from the base config)",
            path.name,
        )
        overlay = {key: value for key, value in overlay.items() if key != "paths"}

    raw_base = {
        "paths": {
            "input_dir": str(base.paths.input_dir),
            "staging_dir": str(base.paths.staging_dir),
            "output_dir": str(base.paths.output_dir),
            "runs_dir": str(base.paths.runs_dir),
        },
        "chunking": asdict(base.chunking),
        "selection": asdict(base.selection),
        "llm": asdict(base.llm),
        "tts": asdict(base.tts),
        "output": asdict(base.output),
        "pipeline": asdict(base.pipeline),
    }
    merged = deep_merge(raw_base, overlay)
    logger.info("Applied book config overlay: %s", path)
    resolved = app_config_from_dict(merged, config_path=base.config_path)
    # Paths were already absolute in raw_base; re-resolve is a no-op for abs paths.
    return resolved


def with_speak_footnote_cues(config: AppConfig, enabled: bool) -> AppConfig:
    """Return a copy with output.speak_footnote_cues set."""
    return replace(config, output=replace(config.output, speak_footnote_cues=enabled))
