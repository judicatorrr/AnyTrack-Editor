ANYTRACK EDITOR 0.12.8 — LINUX

1. Install Python 3.11-3.13 and its venv module.
   Debian/Ubuntu example: sudo apt install python3 python3-venv libxcb-cursor0
2. Run: chmod +x Linux/start_linux.sh
3. Run: ./Linux/start_linux.sh
4. The first launch downloads dependencies; later launches use Linux/.venv.

To build a Linux executable folder, run ./Linux/build_linux.sh on Linux.
The result appears in Linux/dist/AnyTrack Editor/.

Linux packages are distribution-specific. If Qt reports a missing xcb library,
install the matching X11/xcb compatibility package supplied by your distribution.

Optional local routing is installed from Settings. GraphHopper, portable Java
and the selected OpenStreetMap region are stored separately from the program.
