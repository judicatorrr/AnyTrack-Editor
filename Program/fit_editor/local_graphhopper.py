"""Install, prepare and run a private GraphHopper instance on localhost."""
from __future__ import annotations

import os
import platform
import re
import json
import shutil
import socket
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtNetwork

from . import __version__


GRAPHHOPPER_VERSION = "11.0"
GRAPHHOPPER_JAR_URL = (
    "https://repo1.maven.org/maven2/com/graphhopper/graphhopper-web/"
    f"{GRAPHHOPPER_VERSION}/graphhopper-web-{GRAPHHOPPER_VERSION}.jar"
)
LOCAL_HOST = "127.0.0.1"
LOCAL_PORT = 8989
LOCAL_ROUTE_URL = f"http://{LOCAL_HOST}:{LOCAL_PORT}/route"
GRAPH_SCHEMA_VERSION = 2


def _graphhopper_error_summary(output: str, exit_code: int) -> str:
    """Extract the useful root cause instead of the final Java stack frame."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    caused_by = [line for line in lines if line.startswith("Caused by:")]
    if caused_by:
        return caused_by[-1].removeprefix("Caused by:").strip()
    exceptions = [
        line for line in lines
        if re.match(r"(?:[\w.$]+\.)*[\w$]*(?:Exception|Error):", line)
    ]
    if exceptions:
        return exceptions[-1]
    route_listing = re.compile(
        r"^(?:GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\s+/\S+(?:\s+\([^)]*\))?$"
    )
    useful = [
        line for line in lines
        if not line.startswith("at ")
        and not re.match(r"^(INFO|DEBUG|TRACE)\s", line)
        and not route_listing.match(line)
    ]
    return useful[-1] if useful else f"GraphHopper exited with code {exit_code}."


def _adoptium_runtime_url() -> str:
    system = platform.system().lower()
    operating_system = {"windows": "windows", "darwin": "mac"}.get(system, "linux")
    machine = platform.machine().lower()
    architecture = "aarch64" if machine in {"arm64", "aarch64"} else "x64"
    return (
        "https://api.adoptium.net/v3/binary/latest/25/ga/"
        f"{operating_system}/{architecture}/jre/hotspot/normal/eclipse"
    )


def _java_major_version(executable: str) -> int:
    try:
        result = subprocess.run(
            [executable, "-version"],
            capture_output=True,
            text=True,
            timeout=4,
            check=False,
            creationflags=(
                subprocess.CREATE_NO_WINDOW
                if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW")
                else 0
            ),
        )
    except (OSError, subprocess.SubprocessError):
        return 0
    match = re.search(r'version\s+"(?:1\.)?(\d+)', result.stderr + result.stdout)
    return int(match.group(1)) if match else 0


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with zipfile.ZipFile(archive) as source:
        for member in source.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise ValueError("The runtime archive contains an unsafe path.")
        source.extractall(destination)


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    root = destination.resolve()
    with tarfile.open(archive, "r:gz") as source:
        for member in source.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ValueError("The runtime archive contains an unsafe path.")
        if "filter" in tarfile.TarFile.extractall.__code__.co_varnames:
            source.extractall(destination, filter="data")
        else:
            source.extractall(destination)


class _RuntimeExtractor(QtCore.QThread):
    succeeded = QtCore.Signal(str)
    failed = QtCore.Signal(str)

    def __init__(self, archive: Path, runtime_dir: Path, parent=None):
        super().__init__(parent)
        self.archive = archive
        self.runtime_dir = runtime_dir

    def run(self) -> None:
        temporary = self.runtime_dir.with_name(self.runtime_dir.name + "-extracting")
        try:
            if temporary.exists():
                shutil.rmtree(temporary)
            temporary.mkdir(parents=True)
            if self.archive.suffix.lower() == ".zip":
                _safe_extract_zip(self.archive, temporary)
            else:
                _safe_extract_tar(self.archive, temporary)
            java_name = "java.exe" if sys.platform == "win32" else "java"
            candidates = list(temporary.rglob(java_name))
            candidates = [item for item in candidates if item.parent.name == "bin"]
            if not candidates:
                raise ValueError("Java was not found in the downloaded runtime archive.")
            java_home = candidates[0].parent.parent
            if self.runtime_dir.exists():
                shutil.rmtree(self.runtime_dir)
            shutil.move(str(java_home), str(self.runtime_dir))
            shutil.rmtree(temporary, ignore_errors=True)
            self.archive.unlink(missing_ok=True)
            self.succeeded.emit(str(self.runtime_dir))
        except Exception as error:
            shutil.rmtree(temporary, ignore_errors=True)
            self.failed.emit(str(error))


class LocalGraphHopperManager(QtCore.QObject):
    """Own the optional engine, its map graph and the localhost process."""

    stateChanged = QtCore.Signal(str, str)
    progressChanged = QtCore.Signal(int, str)
    downloadBytesChanged = QtCore.Signal(int, int, str)
    componentsChanged = QtCore.Signal()
    prepared = QtCore.Signal()
    ready = QtCore.Signal()
    failed = QtCore.Signal(str)

    def __init__(self, settings: QtCore.QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        default_root = Path(
            QtCore.QStandardPaths.writableLocation(
                QtCore.QStandardPaths.StandardLocation.AppLocalDataLocation
            )
        ) / "graphhopper"
        self.root = Path(str(settings.value("local_graphhopper_root", default_root)))
        self.pbf_path = Path(str(settings.value("local_graphhopper_pbf", "")))
        self.memory_gb = max(2, int(settings.value("local_graphhopper_memory_gb", 4) or 4))
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self._read_process_output)
        self.process.finished.connect(self._process_finished)
        self._operation = ""
        self._last_output = ""
        self._import_progress = 0
        self._ready_callbacks: list[Callable[[], None]] = []
        self._ready_deadline = 0.0
        self._poll_timer = QtCore.QTimer(self)
        self._poll_timer.setInterval(350)
        self._poll_timer.timeout.connect(self._poll_server)
        self._network = QtNetwork.QNetworkAccessManager(self)
        self._download_reply: QtNetwork.QNetworkReply | None = None
        self._download_file: QtCore.QSaveFile | None = None
        self._download_kind = ""
        self._download_destination: Path | None = None
        self._install_queue: list[str] = []
        self._extractor: _RuntimeExtractor | None = None

    @property
    def jar_path(self) -> Path:
        return self.root / f"graphhopper-web-{GRAPHHOPPER_VERSION}.jar"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def config_path(self) -> Path:
        return self.root / "config.yml"

    @property
    def graph_dir(self) -> Path:
        return self.root / "graph-cache"

    @property
    def log_path(self) -> Path:
        return self.root / "graphhopper.log"

    @property
    def graph_schema_path(self) -> Path:
        return self.root / "graph-schema.json"

    def set_root(self, value: str | Path) -> None:
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            raise RuntimeError("Stop GraphHopper before changing its data folder.")
        self.root = Path(value).expanduser().resolve()
        self.settings.setValue("local_graphhopper_root", str(self.root))
        self.componentsChanged.emit()

    def set_pbf_path(self, value: str | Path) -> None:
        self.pbf_path = Path(value).expanduser().resolve()
        self.settings.setValue("local_graphhopper_pbf", str(self.pbf_path))
        self.componentsChanged.emit()

    def downloaded_map_files(self, slug: str) -> list[Path]:
        """Return app-managed extracts, including files from pre-0.12.6 builds."""
        slug = Path(slug).name
        candidates: list[Path] = []
        for folder in (self.root / "maps", self.root):
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob(f"{slug}*.osm.pbf")):
                try:
                    resolved = path.resolve()
                    if resolved.is_file() and resolved not in candidates:
                        candidates.append(resolved)
                except OSError:
                    continue
        return candidates

    def delete_downloaded_map(self, slug: str) -> int:
        """Delete one downloaded region and its graph when it is the active source."""
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            raise RuntimeError("Stop GraphHopper before deleting a routing map.")
        targets = self.downloaded_map_files(slug)
        if not targets:
            return 0
        try:
            current = self.pbf_path.resolve() if self.pbf_path.is_file() else None
        except OSError:
            current = None
        active_deleted = current is not None and current in targets
        removed = 0
        for path in targets:
            path.unlink()
            removed += 1
        if active_deleted:
            if self.graph_dir.is_dir():
                shutil.rmtree(self.graph_dir)
            self.graph_schema_path.unlink(missing_ok=True)
            self.pbf_path = Path("")
            self.settings.remove("local_graphhopper_pbf")
        self.componentsChanged.emit()
        self.emit_current_state()
        return removed

    def set_memory_gb(self, value: int) -> None:
        self.memory_gb = max(2, int(value))
        self.settings.setValue("local_graphhopper_memory_gb", self.memory_gb)

    def bundled_java_path(self) -> Path:
        name = "java.exe" if sys.platform == "win32" else "java"
        return self.runtime_dir / "bin" / name

    def java_command(self) -> str:
        bundled = self.bundled_java_path()
        if bundled.is_file() and _java_major_version(str(bundled)) >= 25:
            return str(bundled)
        system_java = shutil.which("java") or ""
        if system_java and _java_major_version(system_java) >= 25:
            return system_java
        return ""

    def components_installed(self) -> bool:
        return self.jar_path.is_file() and bool(self.java_command())

    def graph_prepared(self) -> bool:
        try:
            return self.graph_dir.is_dir() and any(self.graph_dir.iterdir())
        except OSError:
            return False

    def graph_requires_rebuild(self) -> bool:
        """Return whether an existing graph predates the elevation-enabled schema."""
        if not self.graph_prepared():
            return False
        try:
            metadata = json.loads(self.graph_schema_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return True
        return not (
            int(metadata.get("schema", 0)) == GRAPH_SCHEMA_VERSION
            and metadata.get("elevation") is True
            and Path(str(metadata.get("source", ""))).resolve() == self.pbf_path.resolve()
        )

    def _write_graph_schema(self) -> None:
        payload = {
            "schema": GRAPH_SCHEMA_VERSION,
            "elevation": True,
            "graphhopper": GRAPHHOPPER_VERSION,
            "source": str(self.pbf_path),
        }
        self.graph_schema_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def installation_size(self) -> int:
        total = 0
        if not self.root.exists():
            return 0
        for path in self.root.rglob("*"):
            try:
                if path.is_file():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    def is_running(self) -> bool:
        try:
            with socket.create_connection((LOCAL_HOST, LOCAL_PORT), timeout=0.08):
                return True
        except OSError:
            return False

    def state(self) -> str:
        if self._download_reply is not None:
            return "downloading"
        if self._extractor is not None and self._extractor.isRunning():
            return "extracting"
        if self._operation == "import" and self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            return "importing"
        if self.is_running():
            return "running"
        if not self.components_installed():
            return "not_installed"
        if not self.pbf_path.is_file():
            return "needs_map"
        if not self.graph_prepared():
            return "needs_prepare"
        if self.graph_requires_rebuild():
            return "needs_rebuild"
        return "stopped"

    def emit_current_state(self, details: str = "") -> None:
        self.stateChanged.emit(self.state(), details)

    def install_components(self) -> None:
        if self._download_reply is not None or (
            self._extractor is not None and self._extractor.isRunning()
        ):
            return
        self.root.mkdir(parents=True, exist_ok=True)
        self._install_queue = []
        if not self.jar_path.is_file():
            self._install_queue.append("engine")
        if not self.java_command():
            self._install_queue.append("runtime")
        if not self._install_queue:
            self.componentsChanged.emit()
            self.emit_current_state()
            return
        self._download_next_component()

    def _download_next_component(self) -> None:
        if not self._install_queue:
            self.progressChanged.emit(100, "installed")
            self.componentsChanged.emit()
            self.emit_current_state()
            return
        kind = self._install_queue.pop(0)
        self._download_kind = kind
        if kind == "engine":
            url = GRAPHHOPPER_JAR_URL
            destination = self.jar_path
        else:
            url = _adoptium_runtime_url()
            destination = self.root / ("runtime.zip" if sys.platform == "win32" else "runtime.tar.gz")
        destination.parent.mkdir(parents=True, exist_ok=True)
        self._download_destination = destination
        save_file = QtCore.QSaveFile(str(destination))
        if not save_file.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
            self._fail(f"Could not create {destination}")
            return
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        request.setAttribute(
            QtNetwork.QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QtNetwork.QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setRawHeader(
            b"User-Agent", f"AnyTrack-Editor/{__version__}".encode("ascii")
        )
        self._download_file = save_file
        self._download_reply = self._network.get(request)
        self._download_reply.readyRead.connect(self._download_ready_read)
        self._download_reply.downloadProgress.connect(self._download_progress)
        self._download_reply.finished.connect(self._download_finished)
        self.stateChanged.emit("downloading", kind)

    def download_map(self, url: str, filename: str) -> None:
        """Download an official .osm.pbf extract into the private data folder."""
        if self._download_reply is not None:
            raise RuntimeError("Another download is already in progress.")
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            raise RuntimeError("Stop the local GraphHopper process before downloading a map.")
        safe_name = Path(filename).name
        if not safe_name.lower().endswith(".osm.pbf"):
            raise ValueError("The downloaded map must be an .osm.pbf file.")
        destination = self.root / "maps" / safe_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        save_file = QtCore.QSaveFile(str(destination))
        if not save_file.open(QtCore.QIODevice.OpenModeFlag.WriteOnly):
            self._fail(f"Could not create {destination}")
            return
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        request.setAttribute(
            QtNetwork.QNetworkRequest.Attribute.RedirectPolicyAttribute,
            QtNetwork.QNetworkRequest.RedirectPolicy.NoLessSafeRedirectPolicy,
        )
        request.setRawHeader(
            b"User-Agent", f"AnyTrack-Editor/{__version__}".encode("ascii")
        )
        self._download_kind = "map"
        self._download_destination = destination
        self._download_file = save_file
        self._download_reply = self._network.get(request)
        self._download_reply.readyRead.connect(self._download_ready_read)
        self._download_reply.downloadProgress.connect(self._download_progress)
        self._download_reply.finished.connect(self._download_finished)
        self.stateChanged.emit("downloading", "map")
        self.progressChanged.emit(0, "map")
        self.downloadBytesChanged.emit(0, 0, "map")

    def _download_ready_read(self) -> None:
        if self._download_reply is not None and self._download_file is not None:
            self._download_file.write(self._download_reply.readAll())

    def _download_progress(self, received: int, total: int) -> None:
        percent = int(received * 100 / total) if total > 0 else -1
        self.progressChanged.emit(percent, self._download_kind)
        self.downloadBytesChanged.emit(received, total, self._download_kind)

    def _download_finished(self) -> None:
        reply = self._download_reply
        save_file = self._download_file
        kind = self._download_kind
        destination = self._download_destination
        self._download_reply = None
        self._download_file = None
        self._download_destination = None
        if reply is None or save_file is None:
            return
        if reply.error() != QtNetwork.QNetworkReply.NetworkError.NoError:
            message = reply.errorString()
            save_file.cancelWriting()
            reply.deleteLater()
            self._fail(message)
            return
        if not save_file.commit():
            reply.deleteLater()
            self._fail("Could not save the downloaded component.")
            return
        reply.deleteLater()
        if kind == "map":
            if destination is None:
                self._fail("The downloaded map destination is missing.")
                return
            self.set_pbf_path(destination)
            # Even when the stable *-latest filename is unchanged, its OSM
            # contents have advanced and the prepared graph must be rebuilt.
            self.graph_schema_path.unlink(missing_ok=True)
            self.progressChanged.emit(100, "map")
            self.emit_current_state("map_downloaded")
            return
        if kind == "runtime":
            archive = self.root / ("runtime.zip" if sys.platform == "win32" else "runtime.tar.gz")
            self.stateChanged.emit("extracting", "runtime")
            self.progressChanged.emit(-1, "runtime")
            self._extractor = _RuntimeExtractor(archive, self.runtime_dir, self)
            self._extractor.succeeded.connect(self._runtime_extracted)
            self._extractor.failed.connect(self._runtime_extract_failed)
            self._extractor.start()
        else:
            self._download_next_component()

    def _runtime_extracted(self, _path: str) -> None:
        if self._extractor is not None:
            self._extractor.deleteLater()
        self._extractor = None
        self._download_next_component()

    def _runtime_extract_failed(self, message: str) -> None:
        if self._extractor is not None:
            self._extractor.deleteLater()
        self._extractor = None
        self._fail(message)

    def cancel_install(self) -> None:
        self._install_queue.clear()
        if self._download_reply is not None:
            self._download_reply.abort()

    @staticmethod
    def _yaml_path(path: Path) -> str:
        return path.resolve().as_posix().replace("'", "''")

    def write_config(self) -> Path:
        if not self.pbf_path.is_file():
            raise FileNotFoundError("Select an OpenStreetMap .osm.pbf file first.")
        self.root.mkdir(parents=True, exist_ok=True)
        pbf = self._yaml_path(self.pbf_path)
        graph = self._yaml_path(self.graph_dir)
        elevation_cache = self._yaml_path(self.root / "elevation-cache")
        config = f"""graphhopper:
  datareader.file: '{pbf}'
  graph.location: '{graph}'
  graph.elevation.provider: srtm
  graph.elevation.cache_dir: '{elevation_cache}'
  graph.elevation.interpolate: bilinear
  import.osm.ignored_highways: ''
  profiles:
    - name: bike
      custom_model_files: [bike.json]
    - name: racingbike
      custom_model_files: [racingbike.json]
    - name: mtb
      custom_model_files: [mtb.json]
    - name: foot
      custom_model_files: [foot.json]
    - name: car
      custom_model_files: [car.json]
  graph.encoded_values: |
    car_access, car_average_speed, country, road_class, roundabout, max_speed, road_environment,
    foot_access, foot_average_speed, foot_priority, foot_road_access, hike_rating, average_slope,
    bike_access, bike_average_speed, bike_priority, bike_road_access, bike_network, mtb_rating,
    ferry_speed, racingbike_priority, racingbike_access, racingbike_average_speed,
    mtb_priority, mtb_access, mtb_average_speed
  profiles_ch: []
  profiles_lm: []

server:
  application_connectors:
    - type: http
      port: {LOCAL_PORT}
      bind_host: {LOCAL_HOST}
  admin_connectors:
    - type: http
      port: 8990
      bind_host: {LOCAL_HOST}
  request_log:
    appenders: []
"""
        self.config_path.write_text(config, encoding="utf-8")
        return self.config_path

    def prepare_map(self) -> None:
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            return
        try:
            java = self.java_command()
            if not java or not self.jar_path.is_file():
                raise RuntimeError("Install the local GraphHopper components first.")
            config = self.write_config()
        except Exception as error:
            self._fail(str(error))
            return
        self._operation = "import"
        self._last_output = ""
        self._import_progress = 2
        self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(java)
        self.process.setArguments([
            f"-Xmx{self.memory_gb}g", "-jar", str(self.jar_path),
            "import", str(config),
        ])
        self.process.start()
        self.progressChanged.emit(self._import_progress, "import")
        self.stateChanged.emit("importing", "")

    def start_service(self) -> None:
        if self.is_running():
            self._server_ready()
            return
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            return
        try:
            java = self.java_command()
            if not java or not self.jar_path.is_file():
                raise RuntimeError("Install the local GraphHopper components first.")
            if not self.graph_prepared():
                raise RuntimeError("Prepare the selected OpenStreetMap map first.")
            if self.graph_requires_rebuild():
                raise RuntimeError(
                    "The route database was created without elevation support. "
                    "Prepare the map again once before starting GraphHopper."
                )
            config = self.write_config()
        except Exception as error:
            self._fail(str(error))
            return
        self._operation = "server"
        self._last_output = ""
        self.process.setWorkingDirectory(str(self.root))
        self.process.setProgram(java)
        self.process.setArguments([
            f"-Xmx{self.memory_gb}g", "-jar", str(self.jar_path),
            "server", str(config),
        ])
        self.process.start()
        self._ready_deadline = time.monotonic() + 90.0
        self._poll_timer.start()
        self.stateChanged.emit("starting", "")

    def ensure_running(self, callback: Callable[[], None]) -> None:
        if self.is_running():
            QtCore.QTimer.singleShot(0, callback)
            return
        if callback not in self._ready_callbacks:
            self._ready_callbacks.append(callback)
        self.start_service()

    def test_connection(self) -> bool:
        running = self.is_running()
        self.stateChanged.emit("running" if running else self.state(), "test")
        return running

    def _poll_server(self) -> None:
        if self.is_running():
            self._server_ready()
            return
        if time.monotonic() >= self._ready_deadline:
            self._poll_timer.stop()
            self._ready_callbacks.clear()
            self._fail("GraphHopper did not start within 90 seconds.")

    def _server_ready(self) -> None:
        self._poll_timer.stop()
        self.stateChanged.emit("running", "")
        self.ready.emit()
        callbacks = self._ready_callbacks[:]
        self._ready_callbacks.clear()
        for callback in callbacks:
            QtCore.QTimer.singleShot(0, callback)

    def stop_service(self) -> None:
        self._ready_callbacks.clear()
        self._poll_timer.stop()
        if self.process.state() == QtCore.QProcess.ProcessState.NotRunning:
            self.emit_current_state()
            return
        # A user-requested stop is not a GraphHopper crash. Clear the active
        # operation before terminate(), otherwise QProcess.finished would show
        # a misleading error dialog for the expected non-zero exit code.
        self._operation = ""
        self.stateChanged.emit("stopping", "")
        self.process.terminate()
        QtCore.QTimer.singleShot(
            3000,
            lambda: self.process.kill()
            if self.process.state() != QtCore.QProcess.ProcessState.NotRunning
            else None,
        )

    def delete_graph_cache(self) -> None:
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            raise RuntimeError("Stop GraphHopper before deleting its route database.")
        if self.graph_dir.is_dir():
            shutil.rmtree(self.graph_dir)
        self.graph_schema_path.unlink(missing_ok=True)
        self.componentsChanged.emit()
        self.emit_current_state()

    def _read_process_output(self) -> None:
        text = bytes(self.process.readAllStandardOutput()).decode("utf-8", "replace")
        self._last_output = (self._last_output + text)[-12_000:]
        if self._operation == "import":
            stages = (
                ("pass1 - start", 12),
                ("pass1 - finished", 32),
                ("pass2 - start", 40),
                ("pass2 - finished", 68),
                ("Start marking subnetworks", 76),
                ("Finished finding and marking subnetworks", 88),
                ("location index created", 94),
                ("flushing graph", 98),
            )
            for marker, percent in stages:
                if marker in text and percent > self._import_progress:
                    self._import_progress = percent
                    self.progressChanged.emit(percent, "import")
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as log:
                log.write(text)
        except OSError:
            pass

    def _process_finished(self, exit_code: int, _exit_status) -> None:
        operation = self._operation
        self._operation = ""
        self._poll_timer.stop()
        if operation == "import" and exit_code == 0 and self.graph_prepared():
            try:
                self._write_graph_schema()
            except OSError as error:
                self._fail(f"Could not save the route database schema: {error}")
                return
            self.progressChanged.emit(100, "import")
            self.componentsChanged.emit()
            self.prepared.emit()
            self.stateChanged.emit("stopped", "prepared")
            return
        if operation == "server" and exit_code == 0:
            self.emit_current_state()
            return
        if operation:
            self._fail(_graphhopper_error_summary(self._last_output, exit_code))
            return
        self.emit_current_state()

    def _fail(self, message: str) -> None:
        self._install_queue.clear()
        self.progressChanged.emit(0, "error")
        self.stateChanged.emit("error", message)
        self.failed.emit(message)

    def shutdown(self) -> None:
        self.cancel_install()
        self.stop_service()
