"""JSON configuration: dataclasses + load_config() with a baked-in default path."""

import json
import logging
import os
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_TOOL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = _TOOL_ROOT / "config.json"
EXPERIMENT_CONFIG_PATH = _TOOL_ROOT.parent / "epub-to-audiobook/config.json"

DEFAULT_CLEAN_PROMPT = (
    "Clean this text for text-to-speech. Remove URLs, expand abbreviations, "
    "and improve phonetic readability. Return only the cleaned text, no commentary.\n\n"
    "Text:\n{text}"
)


@dataclass
class PathsConfig:
    epub_dir: Path = Path("data/input")
    staging_dir: Path = Path("data/staging")
    output_dir: Path = Path("data/output")
    runs_dir: Path = Path("data/runs")

    def resolve_against(self, base: Path) -> None:
        """Resolve relative paths against the config file's directory."""
        for name in ("epub_dir", "staging_dir", "output_dir", "runs_dir"):
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


DEFAULT_JELLYFIN_URL = "http://192.168.0.10:8096"


@dataclass
class PublishConfig:
    """Jellyfin publish settings. Secrets and host paths come from the environment."""

    enabled: bool = False
    mode: str = "auto"
    url: str = DEFAULT_JELLYFIN_URL
    api_key: str | None = None
    library_root: Path | None = None
    rsync_target: str | None = None
    container_path: str | None = None


@dataclass
class AppConfig:
    paths: PathsConfig
    chunking: ChunkingConfig
    selection: SelectionConfig
    llm: LlmConfig
    tts: TtsConfig
    output: OutputConfig
    pipeline: PipelineConfig
    publish: PublishConfig
    config_path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable snapshot for run manifests (API key redacted)."""
        data = _jsonable(asdict(self))
        publish = data.get("publish")
        if isinstance(publish, dict) and publish.get("api_key"):
            publish["api_key"] = "***"
        return data


_SECTIONS: dict[str, type] = {
    "paths": PathsConfig,
    "chunking": ChunkingConfig,
    "selection": SelectionConfig,
    "llm": LlmConfig,
    "tts": TtsConfig,
    "output": OutputConfig,
    "pipeline": PipelineConfig,
    "publish": PublishConfig,
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


def _env_str(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    return raw or None


def _env_bool(name: str) -> bool | None:
    raw = _env_str(name)
    if raw is None:
        return None
    return raw.lower() in {"1", "true", "yes", "on"}


def overlay_publish_env(cfg: PublishConfig) -> PublishConfig:
    """Apply JELLYFIN_* environment variables. Env wins over config.json."""
    url = _env_str("JELLYFIN_URL")
    if url is not None:
        cfg.url = url.rstrip("/")

    api_key = _env_str("JELLYFIN_API_KEY")
    if api_key is not None:
        cfg.api_key = api_key

    library_root = _env_str("JELLYFIN_LIBRARY_ROOT")
    if library_root is not None:
        cfg.library_root = Path(library_root)

    rsync_target = _env_str("JELLYFIN_RSYNC_TARGET")
    if rsync_target is not None:
        cfg.rsync_target = rsync_target

    container_path = _env_str("JELLYFIN_CONTAINER_PATH")
    if container_path is not None:
        cfg.container_path = container_path

    mode = _env_str("JELLYFIN_PUBLISH_MODE")
    if mode is not None:
        cfg.mode = mode.lower()

    if isinstance(cfg.library_root, str):
        cfg.library_root = Path(cfg.library_root) if cfg.library_root else None
    if cfg.api_key == "":
        cfg.api_key = None
    if cfg.rsync_target == "":
        cfg.rsync_target = None
    if cfg.container_path == "":
        cfg.container_path = None
    if cfg.url:
        cfg.url = cfg.url.rstrip("/")

    env_dest = library_root is not None or rsync_target is not None
    publish_flag = _env_bool("JELLYFIN_PUBLISH")
    if publish_flag is False:
        cfg.enabled = False
    elif publish_flag is True:
        cfg.enabled = True
    elif env_dest:
        cfg.enabled = True
    return cfg


def load_config(path: Path | None = None) -> AppConfig:
    """Load an AppConfig from a JSON file (default: the shipped experiment config)."""
    config_path = (Path(path) if path is not None else DEFAULT_CONFIG_PATH).resolve()
    data = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a JSON object: {config_path}")

    for key in sorted(set(data) - set(_SECTIONS)):
        logger.warning("Ignoring unknown config section: %s", key)

    paths = _build_section(PathsConfig, data.get("paths"), "paths")
    paths.resolve_against(config_path.parent)
    publish = overlay_publish_env(_build_section(PublishConfig, data.get("publish"), "publish"))

    return AppConfig(
        paths=paths,
        chunking=_build_section(ChunkingConfig, data.get("chunking"), "chunking"),
        selection=_build_section(SelectionConfig, data.get("selection"), "selection"),
        llm=_build_section(LlmConfig, data.get("llm"), "llm"),
        tts=_build_section(TtsConfig, data.get("tts"), "tts"),
        output=_build_section(OutputConfig, data.get("output"), "output"),
        pipeline=_build_section(PipelineConfig, data.get("pipeline"), "pipeline"),
        publish=publish,
        config_path=config_path,
    )
