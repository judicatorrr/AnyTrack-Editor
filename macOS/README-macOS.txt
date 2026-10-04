ANYTRACK EDITOR 0.12.8 — macOS

1. Install Python 3.11, 3.12 or 3.13 from python.org.
2. Double-click start_macos.command.
3. If macOS blocks the first launch, right-click the file, choose Open and
   confirm. Alternatively run: chmod +x macOS/start_macos.command
4. The first launch downloads dependencies; later launches use macOS/.venv.

To build AnyTrack Editor.app, run build_macos_app.command on a Mac.
The result appears in macOS/dist/AnyTrack Editor.app.

An .app must be assembled on macOS. The supplied source and launcher work on
both Apple Silicon and Intel Macs when the matching Python build is installed.

Optional local routing is installed from Settings. GraphHopper, portable Java
and the selected OpenStreetMap region are stored separately from the program.
