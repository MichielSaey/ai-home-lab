"""JSON configuration: dataclasses + load_config() with a baked-in default path."""

import json
import logging
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TOOL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _TOOL_ROOT / "config.json"
EXPERIMENT_CONFIG_PATH = _TOOL_ROOT.parent / "epub-to-audiobook/config.json"

DEFAULT_CLEAN_PROMPT = (
    "Clean this text for text-to-speech narration. Return only the cleaned text, "
    "no commentary.\n\n"
    "Rules:\n"
    "- Remove URLs.\n"
    "- Spell dates like 03/09/2026 as \"the third of September, twenty twenty-six\".\n"
    "- Expand i.e. and e.i. to \"in other words\", and e.g. to \"for example\".\n"
    "- Delete bibliography, references, works cited, and endnotes sections entirely.\n"
    "- Simplify inline citations. Example: "
    "\"Mark Fisher (2012). Terminator vs Avatar in #Accelerate: The Accelerationist "
    "Reader, Urbanomic, p. 342.\" becomes \"Wrote Mark Fisher in twenty twelve\".\n"
    "- Improve phonetic readability otherwise.\n\n"
    "Text:\n{text}"
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
    words_per_chunk: int = 250
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
    cleanup_batch_size: int = 8
    max_new_tokens: int = 1024
    clean_prompt: str = DEFAULT_CLEAN_PROMPT


@dataclass
class TtsConfig:
    lang: str = "b"
    voice: str = "bf_emma"
    speed: float = 0.92
    device: str = "auto"


@dataclass
class OutputConfig:
    chapter_mp3: bool = False
    mp3_bitrate: str = "128k"
    m4b_bitrate: str = "64k"
    keep_wav: bool = False
    skip_existing: bool = True
    chunk_silence_ms: int = 0
    chapter_silence_ms: int = 0
    loudnorm: bool = False


@dataclass
class PipelineConfig:
    concurrent_models: bool = True
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


def _build_section(cls: type, data: Any, section: str) -> Any:
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ValueError(f"Config section '{section}' must be a JSON object")
    known = {f.name for f in fields(cls)}
    for key in sorted(set(data) - known):
        logger.warning("Ignoring unknown config key: %s.%s", section, key)
    return cls(**{key: value for key, value in data.items() if key in known})


def load_config(path: Path | None = None) -> AppConfig:
    """Load an AppConfig from a JSON file (default: the shipped experiment config)."""
    config_path = (Path(path) if path is not None else DEFAULT_CONFIG_PATH).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a JSON object: {config_path}")

    for key in sorted(set(data) - set(_SECTIONS)):
        logger.warning("Ignoring unknown config section: %s", key)

    paths_data = data.get("paths")
    if isinstance(paths_data, dict):
        paths_data = dict(paths_data)
        # Backward-compatible alias from the EPUB-only era.
        if "input_dir" not in paths_data and "epub_dir" in paths_data:
            paths_data["input_dir"] = paths_data["epub_dir"]
        paths_data.pop("epub_dir", None)
    paths = _build_section(PathsConfig, paths_data, "paths")
    paths.resolve_against(config_path.parent)

    return AppConfig(
        paths=paths,
        chunking=_build_section(ChunkingConfig, data.get("chunking"), "chunking"),
        selection=_build_section(SelectionConfig, data.get("selection"), "selection"),
        llm=_build_section(LlmConfig, data.get("llm"), "llm"),
        tts=_build_section(TtsConfig, data.get("tts"), "tts"),
        output=_build_section(OutputConfig, data.get("output"), "output"),
        pipeline=_build_section(PipelineConfig, data.get("pipeline"), "pipeline"),
        config_path=config_path,
    )
