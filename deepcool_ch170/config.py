"""Panel configuration. The GUI writes this file; the daemon reloads it."""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "display.json"

PAGES = ("cpu", "gpu", "psu")
MODES = ("auto", "cpu", "gpu", "psu")


@dataclass
class Config:
    mode: str = "auto"
    pages: list = field(default_factory=lambda: ["cpu", "gpu", "psu"])
    dwell_sec: int = 5
    update_ms: int = 1000
    fahrenheit: bool = False
    gpu_pci: str = "auto"
    enabled: bool = True
    psu_overhead_w: int = 30
    psu_capacity_w: int = 0

    def normalized(self):
        mode = self.mode if self.mode in MODES else "auto"
        raw_pages = self.pages if isinstance(self.pages, list) else []
        pages = [page for page in raw_pages if page in PAGES]
        if not pages:
            pages = ["cpu", "gpu"]
        return Config(
            mode=mode,
            pages=pages,
            dwell_sec=_clamp(self.dwell_sec, 1, 60),
            update_ms=_clamp(self.update_ms, 200, 5000),
            fahrenheit=self.fahrenheit is True,
            gpu_pci=self.gpu_pci.strip() or "auto",
            enabled=self.enabled is not False,
            psu_overhead_w=_clamp(self.psu_overhead_w, 0, 500),
            psu_capacity_w=_clamp(self.psu_capacity_w, 0, 5000),
        )


def load():
    if not CONFIG_PATH.exists():
        cfg = Config()
        save(cfg)
        return cfg
    try:
        raw = json.loads(CONFIG_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return Config()
    if not isinstance(raw, dict):
        return Config()
    known = Config.__dataclass_fields__
    values = {key: raw[key] for key in known if key in raw}
    return Config(**values).normalized()


def save(cfg):
    cfg = cfg.normalized()
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(cfg), indent=2) + "\n"
    tmp = CONFIG_PATH.with_suffix(".json.tmp")
    tmp.write_text(payload)
    tmp.replace(CONFIG_PATH)
    return cfg


def _clamp(value, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = low
    return max(low, min(high, number))
