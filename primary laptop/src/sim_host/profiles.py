"""Full-graphics presentation settings for the simulation host."""
from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class PresentationProfile:
    quality: str = "Epic"
    width: int = 1280
    height: int = 720
    fps: int = 30
    wind: float = 65.0

    def server_arguments(self, renderer="dx11"):
        if renderer not in {"dx11", "dx12", "vulkan"}:
            raise ValueError("Unsupported renderer")
        return ["-windowed", f"-{renderer}", f"-quality-level={self.quality}",
                f"-ResX={self.width}", f"-ResY={self.height}", f"-fps={self.fps}",
                "-carla-rpc-port=2000", f"-ExecCmds=t.MaxFPS {self.fps}"]

    def server_command_line(self, renderer="dx11"):
        # Unreal expects the switch outside quotes and only its value quoted.
        arguments = []
        for argument in self.server_arguments(renderer):
            flag, separator, value = argument.partition("=")
            arguments.append(f'{flag}="{value}"' if separator and " " in value else argument)
        return " ".join(arguments)


PRESENTATION = PresentationProfile()


def installed_map_path(carla_root, map_name):
    """Resolve an exact cooked world, never a tile or command-line fragment."""
    if not isinstance(map_name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{1,63}", map_name):
        raise ValueError("Map must be a simple installed world name")
    if "_Tile_" in map_name:
        raise ValueError("Select the root world, not an individual map tile")
    maps = Path(carla_root).resolve() / "CarlaUE4/Content/Carla/Maps"
    choices = [maps / f"{map_name}.umap", maps / map_name / f"{map_name}.umap"]
    matches = [path for path in choices if path.is_file() and path.resolve().is_relative_to(maps.resolve())]
    if len(matches) != 1:
        raise ValueError("Map must uniquely identify an installed cooked world")
    return "/Game/Carla/Maps/" + matches[0].relative_to(maps).with_suffix("").as_posix()
